package com.multimodel.safetyrisk.moderation;

import com.multimodel.safetyrisk.moderation.config.L1FilterProperties;
import com.multimodel.safetyrisk.moderation.config.ModerationAsyncProperties;
import com.multimodel.safetyrisk.moderation.config.ModelServiceProperties;
import com.multimodel.safetyrisk.moderation.config.ModerationCacheProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.kafka.annotation.EnableKafka;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableKafka
@EnableScheduling
@EnableConfigurationProperties({
    L1FilterProperties.class,
    ModelServiceProperties.class,
    ModerationCacheProperties.class,
    ModerationAsyncProperties.class
})
public class ModerationApplication {

    public static void main(String[] args) {
        SpringApplication.run(ModerationApplication.class, args);
    }
}
