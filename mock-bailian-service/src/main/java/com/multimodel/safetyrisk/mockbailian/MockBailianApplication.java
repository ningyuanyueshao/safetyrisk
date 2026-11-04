package com.multimodel.safetyrisk.mockbailian;

import com.multimodel.safetyrisk.mockbailian.config.MockScenarioProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(MockScenarioProperties.class)
public class MockBailianApplication {

    public static void main(String[] args) {
        SpringApplication.run(MockBailianApplication.class, args);
    }
}
