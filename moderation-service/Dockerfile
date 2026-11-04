FROM maven:3.9.9-eclipse-temurin-21-alpine AS build
WORKDIR /workspace

COPY pom.xml ./
COPY common-core/pom.xml common-core/pom.xml
COPY moderation-service/pom.xml moderation-service/pom.xml
COPY gateway-service/pom.xml gateway-service/pom.xml
COPY model-service/pom.xml model-service/pom.xml
COPY mock-bailian-service/pom.xml mock-bailian-service/pom.xml
RUN mvn -q -pl moderation-service -am -DskipTests dependency:go-offline

COPY common-core/src common-core/src
COPY moderation-service/src moderation-service/src
RUN mvn -q -pl moderation-service -am -DskipTests package

FROM openjdk:21-jdk-slim
WORKDIR /app
COPY --from=build /workspace/moderation-service/target/moderation-service-0.1.0-SNAPSHOT.jar app.jar
EXPOSE 8081
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
