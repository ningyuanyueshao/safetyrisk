package com.multimodel.safetyrisk.common.api;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotNull;

public class ModerationRequest {

    @NotNull
    private ContentType contentType;

    private String content;

    private String imageUrl;

    private String imageData;

    private String userId;

    public ContentType getContentType() {
        return contentType;
    }

    public void setContentType(ContentType contentType) {
        this.contentType = contentType;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public String getImageUrl() {
        return imageUrl;
    }

    public void setImageUrl(String imageUrl) {
        this.imageUrl = imageUrl;
    }

    public String getImageData() {
        return imageData;
    }

    public void setImageData(String imageData) {
        this.imageData = imageData;
    }

    public String getUserId() {
        return userId;
    }

    public void setUserId(String userId) {
        this.userId = userId;
    }

    @AssertTrue(message = "invalid request payload for contentType")
    public boolean isPayloadValid() {
        if (contentType == null) {
            return false;
        }

        boolean hasText = content != null && !content.isBlank();
        boolean hasImage = (imageUrl != null && !imageUrl.isBlank()) || (imageData != null && !imageData.isBlank());

        if (contentType == ContentType.TEXT) {
            return hasText;
        }
        if (contentType == ContentType.IMAGE) {
            return hasImage;
        }
        return hasText || hasImage;
    }

    public enum ContentType {
        TEXT,
        IMAGE,
        MIXED
    }
}
