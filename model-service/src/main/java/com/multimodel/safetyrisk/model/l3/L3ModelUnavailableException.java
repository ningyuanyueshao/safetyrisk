package com.multimodel.safetyrisk.model.l3;

/**
 * Indicates that an L3 provider could not produce a trustworthy decision.
 * The failover service uses this signal to try the next provider.
 */
public class L3ModelUnavailableException extends RuntimeException {

    public L3ModelUnavailableException(String message) {
        super(message);
    }

    public L3ModelUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
