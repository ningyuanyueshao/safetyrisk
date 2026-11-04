package com.multimodel.safetyrisk.moderation.persistence;

import com.multimodel.safetyrisk.common.api.ModerationRequest;
import com.multimodel.safetyrisk.moderation.cache.CachedModerationDecision;
import java.util.List;
import reactor.core.publisher.Flux;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

@Service
public class ModerationTaskService {

    private final ModerationTaskRepository taskRepository;

    public ModerationTaskService(ModerationTaskRepository taskRepository) {
        this.taskRepository = taskRepository;
    }

    public Mono<Void> createPendingTask(String taskId, String requestId, String requestHash, ModerationRequest request) {
        return Mono.fromRunnable(() -> taskRepository.insertPending(
                        taskId,
                        requestId,
                        requestHash,
                        request.getContentType().name(),
                        request.getUserId(),
                        request.getContent(),
                        request.getImageUrl(),
                        request.getImageData()))
                .subscribeOn(Schedulers.boundedElastic())
                .then();
    }

    /**
     * 返回 CAS 抢占是否成功；false 表示任务已被并发消费或已完成，调用方应跳过处理。
     */
    public Mono<Boolean> markProcessing(String taskId) {
        return Mono.fromCallable(() -> taskRepository.markProcessing(taskId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    public Mono<Boolean> markCompleted(String taskId, CachedModerationDecision decision) {
        return Mono.fromCallable(() -> taskRepository.markCompleted(taskId, decision))
                .subscribeOn(Schedulers.boundedElastic());
    }

    public Mono<Boolean> markFailed(String taskId, String errorMessage) {
        return Mono.fromCallable(() -> taskRepository.markFailed(taskId, errorMessage))
                .subscribeOn(Schedulers.boundedElastic());
    }

    public Mono<Boolean> markPendingFailed(String taskId, String errorMessage) {
        return Mono.fromCallable(() -> taskRepository.markPendingFailed(taskId, errorMessage))
                .subscribeOn(Schedulers.boundedElastic());
    }

    public Mono<Boolean> touchPendingTask(String taskId) {
        return Mono.fromCallable(() -> taskRepository.touchPendingTask(taskId))
                .subscribeOn(Schedulers.boundedElastic());
    }

    public Flux<ModerationTaskRecord> findOrphanPendingTasks(int limit, long orphanThresholdMs) {
        return Mono.fromCallable(() -> taskRepository.findOrphanPendingTasks(limit, orphanThresholdMs))
                .subscribeOn(Schedulers.boundedElastic())
                .flatMapMany(Flux::fromIterable);
    }

    public Mono<ModerationTaskRecord> findByTaskId(String taskId) {
        return Mono.fromCallable(() -> taskRepository.findByTaskId(taskId))
                .subscribeOn(Schedulers.boundedElastic())
                .flatMap(optional -> optional.map(Mono::just).orElseGet(Mono::empty));
    }

    public Mono<ModerationTaskRecord> findLatestReusableByRequestHash(String requestHash) {
        return Mono.fromCallable(() -> taskRepository.findLatestReusableByRequestHash(requestHash))
                .subscribeOn(Schedulers.boundedElastic())
                .flatMap(optional -> optional.map(Mono::just).orElseGet(Mono::empty));
    }

    public Flux<ModerationTaskRecord> findLatestFailedTasks(int limit) {
        return Mono.fromCallable(() -> taskRepository.findLatestFailedTasks(limit))
                .subscribeOn(Schedulers.boundedElastic())
                .flatMapMany(Flux::fromIterable);
    }
}
