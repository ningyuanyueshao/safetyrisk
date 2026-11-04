package com.multimodel.safetyrisk.model.l2;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import ai.onnxruntime.OrtSession.Result;
import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.model.config.L2ImageModelProperties;
import jakarta.annotation.PostConstruct;

import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.net.URI;
import java.net.URLConnection;
import java.nio.FloatBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;
import javax.imageio.ImageIO;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

@Service
public class OnnxImageClassificationService implements L2ImageClassificationService {

    private static final Logger log = LoggerFactory.getLogger(OnnxImageClassificationService.class);

    // ResNet50 标准输入参数
    private static final int IMAGE_SIZE = 224;
    private static final int CHANNELS = 3;
    // ImageNet 标准化参数
    private static final float[] MEAN = {0.485f, 0.456f, 0.406f};
    private static final float[] STD = {0.229f, 0.224f, 0.225f};

    private final L2ImageModelProperties properties;
    private volatile OrtEnvironment environment;
    private volatile OrtSession session;
    private volatile String inputName;

    public OnnxImageClassificationService(L2ImageModelProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    public void init() {
        if (!properties.isEnabled()) {
            log.info("Model-service L2 image disabled");
            return;
        }
        try {
            Optional<Path> resolved = OnnxModelPathResolver.resolve(properties.getModelPath());
            if (resolved.isEmpty()) {
                log.warn("L2 image model missing, fallback enabled. configuredPath={}", properties.getModelPath());
                return;
            }
            Path modelPath = resolved.get();
            environment = OrtEnvironment.getEnvironment();
            session = environment.createSession(Files.readAllBytes(modelPath), new OrtSession.SessionOptions());
            inputName = session.getInputNames().stream().findFirst().orElse("pixel_values"); // 注意：HuggingFace导出的ONNX输入名通常是 pixel_values
            log.info("L2 image model loaded from {}", modelPath.toAbsolutePath());
        } catch (Exception ex) {
            log.error("L2 image model init failed, fallback enabled", ex);
            session = null;
            inputName = null;
        }
    }

    @Override
    public Mono<L2Decision> classify(ModerationRequest request) {
        String imageUrl = request.getImageUrl();
        String imageData = request.getImageData();
        if ((imageUrl == null || imageUrl.isBlank()) && (imageData == null || imageData.isBlank())) {
            return Mono.just(new L2Decision(
                    "PASS_TO_L3", false, 0.70, "L2 image skipped: imageUrl and imageData empty."));
        }

        return Mono.fromCallable(() -> {
                    if (session != null && inputName != null) {
                        Optional<L2Decision> onnx = tryOnnxInference(imageUrl, imageData);
                        if (onnx.isPresent()) {
                            return onnx.get();
                        }
                    }
                    return fallbackDecision(imageUrl, imageData);
                })
                .subscribeOn(Schedulers.boundedElastic());
    }

    private Optional<L2Decision> tryOnnxInference(String imageUrl, String imageData) {
        try {
            // The frozen evaluation dataset carries local files as Base64 imageData.
            // Production requests may still supply a remote imageUrl.
            BufferedImage image = loadAndResizeImage(imageUrl, imageData);
            if (image == null) {
                log.warn("Failed to load or parse image input");
                return Optional.empty();
            }

            // 2. 将图片转换为 ONNX 需要的 Float 数组 (CHW 格式并归一化)
            float[] tensorData = preprocessImage(image);

            // 3. 构建 Tensor，Shape 为 [BatchSize=1, Channels=3, Height=224, Width=224]
            long[] shape = new long[]{1, CHANNELS, IMAGE_SIZE, IMAGE_SIZE};
            try (OnnxTensor tensor = OnnxTensor.createTensor(environment, FloatBuffer.wrap(tensorData), shape);
                 Result result = session.run(Map.of(inputName, tensor))) {

                // 4. 解析结果
                double riskScore = parseRiskScore(result);
                return Optional.of(scoreToDecision(riskScore, "L2 image ONNX inference"));
            }
        } catch (Exception ex) {
            log.warn("L2 image inference failed, fallback enabled: {}", ex.getMessage());
            return Optional.empty();
        }
    }

    /**
     * 解析 ResNet50 微调后的二分类输出
     */
    private double parseRiskScore(Result result) throws OrtException {
        Object value = result.get(0).getValue();
        if (value instanceof float[][] logits && logits.length > 0 && logits[0].length >= 2) {
            // logits[0][0] 是 Safe 的得分，logits[0][1] 是 Risk 的得分
            float safeLogit = logits[0][0];
            float riskLogit = logits[0][1];

            // 手动计算 Softmax 获取违规(Risk)的概率
            double maxLogit = Math.max(safeLogit, riskLogit);
            double expSafe = Math.exp(safeLogit - maxLogit);
            double expRisk = Math.exp(riskLogit - maxLogit);

            // 返回 0.0 ~ 1.0 之间的概率值
            return expRisk / (expSafe + expRisk);
        }
        return 0.0;
    }

    /**
     * 下载图片并将其 Resize 到 224x224 (强制转为 RGB 格式)
     */
    BufferedImage loadAndResizeImage(String imageUrl, String imageData) {
        try {
            BufferedImage originalImage;
            if (imageData != null && !imageData.isBlank()) {
                String encoded = imageData.trim();
                int comma = encoded.indexOf(',');
                if (encoded.regionMatches(true, 0, "data:", 0, 5) && comma >= 0) {
                    encoded = encoded.substring(comma + 1);
                }
                byte[] bytes = Base64.getMimeDecoder().decode(encoded);
                originalImage = ImageIO.read(new ByteArrayInputStream(bytes));
            } else {
                URLConnection connection = new URI(imageUrl).toURL().openConnection();
                connection.setConnectTimeout(3_000);
                connection.setReadTimeout(5_000);
                try (var stream = connection.getInputStream()) {
                    originalImage = ImageIO.read(stream);
                }
            }
            if (originalImage == null) {
                return null;
            }

            // 创建 224x224 的空白 RGB 图片
            BufferedImage resizedImage = new BufferedImage(IMAGE_SIZE, IMAGE_SIZE, BufferedImage.TYPE_INT_RGB);
            Graphics2D g2d = resizedImage.createGraphics();

            // 绘制缩放后的图片 (TYPE_INT_RGB 会自动剥离透明通道并填充背景)
            g2d.drawImage(originalImage, 0, 0, IMAGE_SIZE, IMAGE_SIZE, null);
            g2d.dispose();

            return resizedImage;
        } catch (Exception e) {
            log.debug("Error downloading/resizing image: {}", e.getMessage());
            return null;
        }
    }

    /**
     * 图像预处理核心：将 BufferedImage 转换为一维 float 数组。
     * 要求：
     * 1. 颜色值从 0~255 映射到 0.0~1.0
     * 2. 使用 ImageNet 的均值和标准差进行归一化
     * 3. 内存布局转换为 CHW (Channel, Height, Width)
     */
    private float[] preprocessImage(BufferedImage image) {
        float[] tensorData = new float[CHANNELS * IMAGE_SIZE * IMAGE_SIZE];
        int stride = IMAGE_SIZE * IMAGE_SIZE;

        for (int y = 0; y < IMAGE_SIZE; y++) {
            for (int x = 0; x < IMAGE_SIZE; x++) {
                int rgb = image.getRGB(x, y);

                // 提取 R, G, B (0~255)
                float r = ((rgb >> 16) & 0xFF) / 255.0f;
                float g = ((rgb >> 8) & 0xFF) / 255.0f;
                float b = (rgb & 0xFF) / 255.0f;

                // 归一化 (x - mean) / std
                r = (r - MEAN[0]) / STD[0];
                g = (g - MEAN[1]) / STD[1];
                b = (b - MEAN[2]) / STD[2];

                // 按 CHW 格式填充一维数组
                int index = y * IMAGE_SIZE + x;
                tensorData[index] = r;                 // Channel 0 (R)
                tensorData[index + stride] = g;        // Channel 1 (G)
                tensorData[index + 2 * stride] = b;    // Channel 2 (B)
            }
        }
        return tensorData;
    }

    private L2Decision fallbackDecision(String imageUrl, String imageData) {
        String normalized = imageUrl == null ? "" : imageUrl.toLowerCase(Locale.ROOT);
        List<String> hits = properties.getFallbackRiskKeywords().stream()
                .filter(keyword -> !keyword.isBlank())
                .filter(keyword -> normalized.contains(keyword.toLowerCase(Locale.ROOT)))
                .collect(Collectors.toList());

        double score = Math.min(1.0, hits.size() * 0.30 + (normalized.endsWith(".gif") ? 0.10 : 0.0));
        if (hits.isEmpty()) {
            score = 0.20;
        }

        String reason = hits.isEmpty()
                ? "L2 image fallback: no risk keyword matched"
                : "L2 image fallback hits=" + String.join(",", hits);
        if (imageData != null && !imageData.isBlank()) {
            reason += ", source=imageData";
        }
        return scoreToDecision(score, reason);
    }

    private L2Decision scoreToDecision(double score, String reasonPrefix) {
        if (score >= properties.getRejectThreshold()) {
            return new L2Decision("REJECT", true, score, reasonPrefix + ", decision=REJECT");
        }
        if (score >= properties.getReviewThreshold()) {
            return new L2Decision("REVIEW", true, score, reasonPrefix + ", decision=REVIEW");
        }
        return new L2Decision("PASS_TO_L3", false, 1.0 - score, reasonPrefix + ", decision=PASS_TO_L3");
    }

}
