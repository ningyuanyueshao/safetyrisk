package com.multimodel.safetyrisk.model.l2;

import static org.assertj.core.api.Assertions.assertThat;

import com.multimodel.safetyrisk.model.config.L2ImageModelProperties;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

class OnnxImageClassificationServiceTest {

    @Test
    void decodesBareAndDataUrlBase64ImagesFromEvaluationPayloads() throws Exception {
        BufferedImage source = new BufferedImage(2, 3, BufferedImage.TYPE_INT_RGB);
        source.setRGB(0, 0, 0x00FF00);
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        ImageIO.write(source, "png", output);
        String encoded = Base64.getEncoder().encodeToString(output.toByteArray());
        OnnxImageClassificationService service =
                new OnnxImageClassificationService(new L2ImageModelProperties());

        BufferedImage bare = service.loadAndResizeImage(null, encoded);
        BufferedImage dataUrl = service.loadAndResizeImage(null, "data:image/png;base64," + encoded);

        assertThat(bare).isNotNull();
        assertThat(bare.getWidth()).isEqualTo(224);
        assertThat(bare.getHeight()).isEqualTo(224);
        assertThat(dataUrl).isNotNull();
        assertThat(dataUrl.getWidth()).isEqualTo(224);
        assertThat(dataUrl.getHeight()).isEqualTo(224);
    }

    @Test
    void decodesWebpBytesEvenWhenTheDatasetFileUsesAJpgSuffix() throws Exception {
        Path fixture = Path.of("../datasets/l3/eval/assets/l3-img-pass-030.jpg").toAbsolutePath().normalize();
        assertThat(fixture).isRegularFile();
        String encoded = Base64.getEncoder().encodeToString(Files.readAllBytes(fixture));
        OnnxImageClassificationService service =
                new OnnxImageClassificationService(new L2ImageModelProperties());

        BufferedImage decoded = service.loadAndResizeImage(null, encoded);

        assertThat(decoded).isNotNull();
        assertThat(decoded.getWidth()).isEqualTo(224);
        assertThat(decoded.getHeight()).isEqualTo(224);
    }
}
