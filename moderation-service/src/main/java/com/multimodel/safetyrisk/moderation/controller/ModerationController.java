package com.multimodel.safetyrisk.moderation.controller;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.common.api.ModerationResponse;
import com.multimodel.safetyrisk.moderation.async.ModerationTaskMessage;
import com.multimodel.safetyrisk.moderation.async.ModerationTaskProducer;
import com.multimodel.safetyrisk.moderation.cache.ModerationCacheKeyBuilder;
import com.multimodel.safetyrisk.moderation.config.ModerationAsyncProperties;
import com.multimodel.safetyrisk.moderation.controller.dto.AsyncModerationBatchReplayItem;
import com.multimodel.safetyrisk.moderation.controller.dto.AsyncModerationBatchReplayResponse;
import com.multimodel.safetyrisk.moderation.controller.dto.AsyncModerationSubmitResponse;
import com.multimodel.safetyrisk.moderation.controller.dto.AsyncModerationTaskResponse;
import com.multimodel.safetyrisk.moderation.metrics.ModerationAsyncMetrics;
import com.multimodel.safetyrisk.moderation.metrics.ModerationBusinessMetrics;
import com.multimodel.safetyrisk.moderation.persistence.ModerationTaskRecord;
import com.multimodel.safetyrisk.moderation.persistence.ModerationTaskService;
import com.multimodel.safetyrisk.moderation.persistence.ModerationTaskStatus;
import com.multimodel.safetyrisk.moderation.service.ModerationPipelineResult;
import com.multimodel.safetyrisk.moderation.service.ModerationPipelineService;
import jakarta.validation.Valid;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.MediaType;
import org.springframework.http.codec.multipart.FilePart;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

import java.util.Base64;

import static org.springframework.http.HttpStatus.NOT_FOUND;

@RestController
@RequestMapping("/api/v1/moderation")
public class ModerationController {

    private static final Logger log = LoggerFactory.getLogger(ModerationController.class);

    private final ModerationPipelineService pipelineService;
    private final ModerationTaskService taskService;
    private final ModerationTaskProducer taskProducer;
    private final ModerationAsyncProperties asyncProperties;
    private final ModerationAsyncMetrics asyncMetrics;
    private final ModerationBusinessMetrics businessMetrics;

    public ModerationController(
            ModerationPipelineService pipelineService,
            ModerationTaskService taskService,
            ObjectProvider<ModerationTaskProducer> taskProducerProvider,
            ModerationAsyncProperties asyncProperties,
            ModerationAsyncMetrics asyncMetrics,
            ModerationBusinessMetrics businessMetrics) {
        this.pipelineService = pipelineService;
        this.taskService = taskService;
        this.taskProducer = taskProducerProvider.getIfAvailable();
        this.asyncProperties = asyncProperties;
        this.asyncMetrics = asyncMetrics;
        this.businessMetrics = businessMetrics;
    }

    //同步处理（仅使用webflux）
    // 同步审核直接在当前 HTTP 请求内完成：沿着 requestId 进入 pipeline，必要时继续调用 model-service。
    // requestId 用于日志、响应回传和人工排障；真正的 Zipkin trace/span 由 tracing 组件自动维护。
    @PostMapping(value = "/check", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ModerationResponse> check(
            @Valid @RequestBody ModerationRequest request,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId) {

        String finalRequestId = normalizeRequestId(requestId);
        long startNanos = System.nanoTime();

        log.info("Moderation check start requestId={} contentType={} userId={}",
                finalRequestId,
                request.getContentType(),
                request.getUserId());

        return pipelineService.evaluate(request, finalRequestId)
                .map(result -> toSyncResponse(finalRequestId, result))
                .doOnNext(response -> {
                    long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
                    log.info("Moderation check end requestId={} decision={} confidence={} elapsedMs={}",
                            finalRequestId,
                            response.getDecision(),
                            response.getConfidence(),
                            elapsedMs);
                    // 同步链路成功时同时记录“结果分布 + 延迟分布”两类核心业务指标。
                    businessMetrics.recordSyncSuccess(elapsedMs, response.getDecision());
                })
                .doOnError(ex -> {
                    long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
                    log.error("Moderation check error requestId={} elapsedMs={}", finalRequestId, elapsedMs, ex);
                    // 错误单独计数，便于在 Grafana 计算错误率并配置 Prometheus 告警。
                    businessMetrics.incrementSyncError();
                });
    }

    // FormData 上传图片接口
    @PostMapping(value = "/check/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<ModerationResponse> checkWithUpload(
            @RequestPart("image") FilePart imagePart,
            @RequestPart(value = "contentType", required = false) String contentType,
            @RequestPart(value = "content", required = false) String content,
            @RequestPart(value = "userId", required = false) String userId,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId) {

        String finalRequestId = normalizeRequestId(requestId);
        long startNanos = System.nanoTime();

        log.info("Moderation check/upload start requestId={} filename={} userId={}",
                finalRequestId,
                imagePart.filename(),
                userId);

        return imagePart.content()
                .reduce((buffer1, buffer2) -> buffer1.write(buffer2))
                .flatMap(dataBuffer -> {
                    byte[] bytes = new byte[dataBuffer.readableByteCount()];
                    dataBuffer.read(bytes);
                    String base64Image = Base64.getEncoder().encodeToString(bytes);

                    ModerationRequest request = new ModerationRequest();
                    request.setContentType(contentType != null && contentType.equalsIgnoreCase("MIXED")
                            ? ModerationRequest.ContentType.MIXED
                            : ModerationRequest.ContentType.IMAGE);
                    request.setContent(content);
                    request.setImageData(base64Image);
                    request.setUserId(userId);

                    return pipelineService.evaluate(request, finalRequestId)
                            .map(result -> toSyncResponse(finalRequestId, result));
                })
                .doOnNext(response -> {
                    long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
                    log.info("Moderation check/upload end requestId={} decision={} confidence={} elapsedMs={}",
                            finalRequestId,
                            response.getDecision(),
                            response.getConfidence(),
                            elapsedMs);
                    businessMetrics.recordSyncSuccess(elapsedMs, response.getDecision());
                })
                .doOnError(ex -> {
                    long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
                    log.error("Moderation check/upload error requestId={} elapsedMs={}", finalRequestId, elapsedMs, ex);
                    businessMetrics.incrementSyncError();
                });
    }

    //异步处理，结合kafka和webflux
    // 异步审核会先把请求写入 Kafka，由消费者异步执行同一条 pipeline。
    // requestHash 用于幂等去重；requestId 仍会保存在任务消息里，方便把入队、消费、回放日志串起来。
    @PostMapping(value = "/check/async", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<AsyncModerationSubmitResponse> submitAsync(
            @Valid @RequestBody ModerationRequest request,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId) {

        if (!asyncProperties.isEnabled()) {
            return Mono.error(new IllegalStateException("Async moderation is disabled by configuration."));
        }
        if (taskProducer == null) {
            return Mono.error(new IllegalStateException("Async producer is unavailable."));
        }

        String finalRequestId = normalizeRequestId(requestId);
        // requestHash 只基于稳定业务内容构造，不能把每次都变化的 requestId 混入缓存/去重键。
        // requestHash 是幂等去重键：同一内容在未处理完成前只保留一个”进行中任务”，
        // 处理完成后命中则直接复用历史结果。
        String requestHash = ModerationCacheKeyBuilder.build(request);
        return enqueueWithDedup(request, finalRequestId, requestHash, "Task accepted and queued to Kafka.");
    }

    @GetMapping(value = "/tasks/{taskId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<AsyncModerationTaskResponse> queryTask(@PathVariable("taskId") String taskId) {
        return taskService.findByTaskId(taskId)
                .switchIfEmpty(Mono.error(new ResponseStatusException(NOT_FOUND, "task not found")))
                .map(this::toTaskResponse)
                .doOnNext(ignored -> businessMetrics.incrementTaskQuery());
    }

    @PostMapping(value = "/tasks/{taskId}/replay", produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<AsyncModerationSubmitResponse> replayTask(
            @PathVariable("taskId") String taskId,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId) {

        if (!asyncProperties.isEnabled()) {
            return Mono.error(new IllegalStateException("Async moderation is disabled by configuration."));
        }
        if (taskProducer == null) {
            return Mono.error(new IllegalStateException("Async producer is unavailable."));
        }

        String finalRequestId = normalizeRequestId(requestId);
        return taskService.findByTaskId(taskId)
                .switchIfEmpty(Mono.error(new ResponseStatusException(NOT_FOUND, "task not found")))
                .flatMap(record -> {
                    // 回放入口只接受 FAILED；避免将正在处理或已完成任务重复入队。
                    if (record.getStatus() != ModerationTaskStatus.FAILED) {
                        return Mono.error(new IllegalStateException("Only FAILED task can be replayed."));
                    }
                    // 回放是“基于任务表重建请求并重新投递原 topic”，而不是直接消费 DLQ topic。
                    ModerationRequest request = toModerationRequest(record);
                    String requestHash = record.getRequestHash() == null || record.getRequestHash().isBlank()
                            ? ModerationCacheKeyBuilder.build(request)
                            : record.getRequestHash();
                    return enqueueWithDedup(request, finalRequestId, requestHash, "Replay task accepted and queued.");
                })
                .doOnNext(ignored -> businessMetrics.incrementReplaySingle());
    }

    @PostMapping(value = "/tasks/replay/batch", produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<AsyncModerationBatchReplayResponse> replayFailedTasks(
            @RequestParam(value = "limit", required = false, defaultValue = "20") int limit,
            @RequestHeader(value = "X-Request-Id", required = false) String requestId) {

        if (!asyncProperties.isEnabled()) {
            return Mono.error(new IllegalStateException("Async moderation is disabled by configuration."));
        }
        if (taskProducer == null) {
            return Mono.error(new IllegalStateException("Async producer is unavailable."));
        }

        int safeLimit = Math.max(1, Math.min(limit, 100));
        String finalRequestId = normalizeRequestId(requestId);

        // 批量回放同样来源于“任务表中的 FAILED 记录”；limit 做上限保护避免瞬时冲击下游。
        return taskService.findLatestFailedTasks(safeLimit)
                .concatMap(record -> {
                    ModerationRequest request = toModerationRequest(record);
                    String requestHash = record.getRequestHash() == null || record.getRequestHash().isBlank()
                            ? ModerationCacheKeyBuilder.build(request)
                            : record.getRequestHash();
                    return enqueueWithDedup(request, finalRequestId, requestHash, "Batch replay task accepted and queued.")
                            .map(submit -> toBatchReplayItem(record.getTaskId(), submit));
                })
                .collectList()
                .map(items -> {
                    AsyncModerationBatchReplayResponse response = new AsyncModerationBatchReplayResponse();
                    response.setRequestId(finalRequestId);
                    response.setRequestedLimit(safeLimit);
                    response.setReplayedCount(items.size());
                    response.setItems(items);
                    businessMetrics.incrementReplayBatch(items.size());
                    return response;
                });
    }

    private String normalizeRequestId(String requestId) {
        return requestId == null || requestId.isBlank() ? UUID.randomUUID().toString() : requestId;
    }

    private ModerationResponse toSyncResponse(String requestId, ModerationPipelineResult result) {
        ModerationResponse response = new ModerationResponse();
        response.setRequestId(requestId);
        response.setViolation(result.getDecision().isViolation());
        response.setDecision(result.getDecision().getDecision());
        response.setConfidence(result.getDecision().getConfidence());
        response.setReason(result.isCacheHit()
                ? result.getDecision().getReason() + " [CACHE_HIT]"
                : result.getDecision().getReason());
        return response;
    }

    private Mono<AsyncModerationSubmitResponse> enqueueWithDedup(
            ModerationRequest request,
            String requestId,
            String requestHash,
            String enqueueMessage) {
        String newTaskId = UUID.randomUUID().toString();
        ModerationTaskMessage message = new ModerationTaskMessage();
        message.setTaskId(newTaskId);
        message.setRequestId(requestId);
        message.setRequest(request);

        return taskService.findLatestReusableByRequestHash(requestHash)
                // 命中去重（进行中/已完成）：复用 taskId 或历史结果，避免重复投递造成任务堆积与重复审核。
                .map(existing -> toReuseResponse(requestId, existing))
                .doOnNext(ignored -> asyncMetrics.incrementDedupHit())
                .switchIfEmpty(taskService.createPendingTask(newTaskId, requestId, requestHash, request)
                        // 先落库再投递：即使 Kafka 发送失败，也能在任务表看到 FAILED 状态，便于排查与回放。
                        .then(taskProducer.send(message)
                                .onErrorResume(ex -> taskService.markFailed(newTaskId, "Kafka enqueue failed: " + ex.getMessage())
                                        .then(Mono.error(ex))))
                        .thenReturn(toEnqueueResponse(requestId, newTaskId, enqueueMessage))
                        .doOnNext(ignored -> asyncMetrics.incrementEnqueue()));
    }

    /**
     * 去重命中响应：已完成任务直接复用历史审核结果；进行中任务复用 taskId，由客户端查询接口轮询结果。
     */
    private AsyncModerationSubmitResponse toReuseResponse(String requestId, ModerationTaskRecord existing) {
        if (existing.getStatus() == ModerationTaskStatus.COMPLETED && existing.getDecision() != null) {
            AsyncModerationSubmitResponse response = toSubmitResponse(
                    requestId, existing.getTaskId(), "COMPLETED", "Task already completed, reuse existing result.");
            response.setDecision(existing.getDecision());
            response.setViolation(existing.getViolation());
            response.setConfidence(existing.getConfidence());
            response.setReason(existing.getReason());
            response.setCompletedAt(existing.getCompletedAt());
            return response;
        }
        return toSubmitResponse(
                requestId, existing.getTaskId(), "PENDING", "Task already queued, reuse existing taskId.");
    }

    private AsyncModerationSubmitResponse toEnqueueResponse(String requestId, String taskId, String message) {
        return toSubmitResponse(requestId, taskId, "PENDING", message);
    }

    private AsyncModerationSubmitResponse toSubmitResponse(
            String requestId,
            String taskId,
            String status,
            String message) {
        AsyncModerationSubmitResponse response = new AsyncModerationSubmitResponse();
        response.setRequestId(requestId);
        response.setTaskId(taskId);
        response.setStatus(status);
        response.setMessage(message);
        return response;
    }

    private ModerationRequest toModerationRequest(ModerationTaskRecord record) {
        ModerationRequest request = new ModerationRequest();
        request.setContentType(ModerationRequest.ContentType.valueOf(record.getContentType()));
        request.setUserId(record.getUserId());
        request.setContent(record.getContent());
        request.setImageUrl(record.getImageUrl());
        request.setImageData(record.getImageData());
        return request;
    }

    private AsyncModerationBatchReplayItem toBatchReplayItem(String sourceTaskId, AsyncModerationSubmitResponse submit) {
        AsyncModerationBatchReplayItem item = new AsyncModerationBatchReplayItem();
        item.setSourceTaskId(sourceTaskId);
        item.setReplayTaskId(submit.getTaskId());
        item.setMessage(submit.getMessage());
        return item;
    }

    private AsyncModerationTaskResponse toTaskResponse(ModerationTaskRecord record) {
        AsyncModerationTaskResponse response = new AsyncModerationTaskResponse();
        response.setTaskId(record.getTaskId());
        response.setRequestId(record.getRequestId());
        response.setStatus(record.getStatus().name());
        response.setDecision(record.getDecision());
        response.setViolation(record.getViolation());
        response.setConfidence(record.getConfidence());
        response.setReason(record.getReason());
        response.setErrorMessage(record.getErrorMessage());
        response.setCreatedAt(record.getCreatedAt());
        response.setUpdatedAt(record.getUpdatedAt());
        response.setCompletedAt(record.getCompletedAt());
        return response;
    }
}
