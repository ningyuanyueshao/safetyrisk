FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace

COPY pom.xml ./
COPY common-core/pom.xml common-core/pom.xml
COPY moderation-service/pom.xml moderation-service/pom.xml
RUN mvn -q -pl moderation-service -am -DskipTests dependency:go-offline

COPY common-core/src common-core/src
COPY moderation-service/src moderation-service/src
RUN mvn -q -pl moderation-service -am -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /workspace/moderation-service/target/moderation-service-0.1.0-SNAPSHOT.jar app.jar
EXPOSE 8081
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
