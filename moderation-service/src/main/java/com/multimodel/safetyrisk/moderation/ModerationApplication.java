package com.multimodel.safetyrisk.moderation;

import com.multimodel.safetyrisk.moderation.config.L1FilterProperties;
import com.multimodel.safetyrisk.moderation.config.ModerationCacheProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties({L1FilterProperties.class, ModerationCacheProperties.class})
public class ModerationApplication {

    public static void main(String[] args) {
        SpringApplication.run(ModerationApplication.class, args);
    }
}
