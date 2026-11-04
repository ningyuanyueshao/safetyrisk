package com.multimodel.safetyrisk.moderation.config;

import com.multimodel.safetyrisk.moderation.metrics.ModerationAsyncMetrics;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.RetryListener;
import org.springframework.util.backoff.FixedBackOff;

@Configuration
@ConditionalOnProperty(prefix = "moderation.async", name = "enabled", havingValue = "true", matchIfMissing = true)
public class ModerationKafkaConfig {

    @Bean(name = "moderationKafkaListenerContainerFactory")
    public ConcurrentKafkaListenerContainerFactory<String, String> moderationKafkaListenerContainerFactory(
            ConsumerFactory<String, String> consumerFactory,
            KafkaTemplate<String, String> kafkaTemplate,
            ModerationAsyncProperties asyncProperties,
            ModerationAsyncMetrics asyncMetrics) {

        ConcurrentKafkaListenerContainerFactory<String, String> factory =
                new ConcurrentKafkaListenerContainerFactory<>();
        factory.setConsumerFactory(consumerFactory);

        DeadLetterPublishingRecoverer recoverer = new DeadLetterPublishingRecoverer(
                kafkaTemplate,
                // 保持原分区投递到 DLQ，便于按分区排查热点/异常消息。
                (record, ex) -> new org.apache.kafka.common.TopicPartition(asyncProperties.getDlqTopic(), record.partition()));

        // maxRetries 表示“失败后的重试次数”，不含首次消费。
        FixedBackOff fixedBackOff = new FixedBackOff(asyncProperties.getRetryBackoffMs(), asyncProperties.getMaxRetries());
        DefaultErrorHandler errorHandler = new DefaultErrorHandler(recoverer, fixedBackOff);
        // 反序列化/消息结构错误通常不可恢复，直接跳过重试进入 DLQ。
        errorHandler.addNotRetryableExceptions(IllegalArgumentException.class);
        errorHandler.setRetryListeners(new RetryListener() {
            @Override
            public void failedDelivery(ConsumerRecord<?, ?> record, Exception ex, int deliveryAttempt) {
                asyncMetrics.incrementRetry();
            }

            @Override
            public void recovered(ConsumerRecord<?, ?> record, Exception ex) {
                asyncMetrics.incrementDlq();
            }
        });

        factory.setCommonErrorHandler(errorHandler);
        return factory;
    }
}
