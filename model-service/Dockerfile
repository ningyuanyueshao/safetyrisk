FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace

COPY pom.xml ./
COPY common-core/pom.xml common-core/pom.xml
COPY model-service/pom.xml model-service/pom.xml
RUN mvn -q -pl model-service -am -DskipTests dependency:go-offline

COPY common-core/src common-core/src
COPY model-service/src model-service/src
RUN mvn -q -pl model-service -am -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /workspace/model-service/target/model-service-0.1.0-SNAPSHOT.jar app.jar
EXPOSE 8082
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
