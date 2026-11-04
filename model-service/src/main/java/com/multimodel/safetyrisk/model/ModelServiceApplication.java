package com.multimodel.safetyrisk.model;

import com.multimodel.safetyrisk.model.config.L2ImageModelProperties;
import com.multimodel.safetyrisk.model.config.L2TextModelProperties;
import com.multimodel.safetyrisk.model.config.L3BailianProperties;
import com.multimodel.safetyrisk.model.config.ModelProtectionProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties({
    L2TextModelProperties.class,
    L2ImageModelProperties.class,
    L3BailianProperties.class,
    ModelProtectionProperties.class
})
public class ModelServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(ModelServiceApplication.class, args);
    }
}
