FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace

COPY pom.xml ./
COPY common-core/pom.xml common-core/pom.xml
COPY gateway-service/pom.xml gateway-service/pom.xml
RUN mvn -q -pl gateway-service -am -DskipTests dependency:go-offline

COPY common-core/src common-core/src
COPY gateway-service/src gateway-service/src
RUN mvn -q -pl gateway-service -am -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /workspace/gateway-service/target/gateway-service-0.1.0-SNAPSHOT.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
