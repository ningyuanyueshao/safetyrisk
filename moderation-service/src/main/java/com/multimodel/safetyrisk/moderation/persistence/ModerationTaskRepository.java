package com.multimodel.safetyrisk.moderation.persistence;

import com.multimodel.safetyrisk.moderation.cache.CachedModerationDecision;
import com.multimodel.safetyrisk.moderation.config.ModerationAsyncProperties;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class ModerationTaskRepository {

    private static final RowMapper<ModerationTaskRecord> ROW_MAPPER = new ModerationTaskRowMapper();

    private final JdbcTemplate jdbcTemplate;
    private final ModerationAsyncProperties asyncProperties;

    public ModerationTaskRepository(JdbcTemplate jdbcTemplate, ModerationAsyncProperties asyncProperties) {
        this.jdbcTemplate = jdbcTemplate;
        this.asyncProperties = asyncProperties;
    }

    public void insertPending(
            String taskId,
            String requestId,
            String requestHash,
            String contentType,
            String userId,
            String content,
            String imageUrl,
            String imageData) {
        String sql = """
                INSERT INTO moderation_task
                (task_id, request_id, request_hash, content_type, user_id, content, image_url, image_data, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())
                """;
        jdbcTemplate.update(sql, taskId, requestId, requestHash, contentType, userId, content, imageUrl, imageData, ModerationTaskStatus.PENDING.name());
    }

    /**
     * CAS 抢占：仅 PENDING/FAILED 可被推进为 PROCESSING。
     * 已被其他消费者抢占（PROCESSING）或已完成（COMPLETED）时返回 false，调用方跳过，不重复审核。
     * 对"卡死在 PROCESSING 的孤儿任务"（消费者处理中崩溃、offset 未提交）按 lease 超时回收，
     * 避免任务永久滞留。返回 true 表示本次成功抢占状态。
     */
    public boolean markProcessing(String taskId) {
        String sql = """
                UPDATE moderation_task
                SET status = ?, updated_at = NOW()
                WHERE task_id = ?
                  AND (
                      status IN (?, ?)
                      OR (status = ? AND updated_at < ?)
                  )
                """;
        return jdbcTemplate.update(sql,
                ModerationTaskStatus.PROCESSING.name(),
                taskId,
                ModerationTaskStatus.PENDING.name(),
                ModerationTaskStatus.FAILED.name(),
                ModerationTaskStatus.PROCESSING.name(),
                new Timestamp(System.currentTimeMillis() - asyncProperties.getProcessingLeaseMs())) > 0;
    }

    /**
     * CAS 完成：仅 PROCESSING 可推进为 COMPLETED（终态），防止并发路径的旧完成结果互相覆盖。
     * 返回 true 表示本次更新实际生效。
     */
    public boolean markCompleted(String taskId, CachedModerationDecision decision) {
        String sql = """
                UPDATE moderation_task
                SET status = ?, decision = ?, violation = ?, confidence = ?, reason = ?,
                    completed_at = NOW(), updated_at = NOW(), error_message = NULL
                WHERE task_id = ?
                  AND status = ?
                """;
        return jdbcTemplate.update(sql,
                ModerationTaskStatus.COMPLETED.name(),
                decision.getDecision(),
                decision.isViolation(),
                decision.getConfidence(),
                decision.getReason(),
                taskId,
                ModerationTaskStatus.PROCESSING.name()) > 0;
    }

    /**
     * CAS 失败：仅 PENDING/PROCESSING 可推进为 FAILED；不覆盖已 COMPLETED 的终态结果。
     * 返回 true 表示本次更新实际生效。
     */
    public boolean markFailed(String taskId, String errorMessage) {
        String sql = """
                UPDATE moderation_task
                SET status = ?, error_message = ?, updated_at = NOW()
                WHERE task_id = ?
                  AND status IN (?, ?)
                """;
        return jdbcTemplate.update(sql,
                ModerationTaskStatus.FAILED.name(),
                truncate(errorMessage),
                taskId,
                ModerationTaskStatus.PENDING.name(),
                ModerationTaskStatus.PROCESSING.name()) > 0;
    }

    /**
     * 清扫孤儿 PENDING：返回停留超过 orphanThresholdMs 的 PENDING 记录，按最旧优先，limit 做批量上限。
     * 正常 PENDING 毫秒级就会被消费者 claim 为 PROCESSING，超时未流转的基本是"落库后从未入队"或"消息进 DLQ 但状态未更新"。
     * 以 updated_at 为超时依据：清扫重投成功后 touch 会刷新 updated_at，天然给重投行为做节流。
     */
    public List<ModerationTaskRecord> findOrphanPendingTasks(int limit, long orphanThresholdMs) {
        String sql = """
                SELECT task_id, request_id, request_hash, content_type, user_id, content, image_url, image_data,
                       status, decision, violation, confidence, reason, error_message,
                       created_at, updated_at, completed_at
                FROM moderation_task
                WHERE status = ?
                  AND updated_at < ?
                ORDER BY updated_at ASC
                LIMIT ?
                """;
        return jdbcTemplate.query(
                sql,
                ROW_MAPPER,
                ModerationTaskStatus.PENDING.name(),
                new Timestamp(System.currentTimeMillis() - orphanThresholdMs),
                limit);
    }

    /**
     * 刷新 PENDING 的 updated_at：清扫重投成功后调用，避免下一轮立即重复清扫。
     * 仅对仍为 PENDING 的记录生效——若已被消费者抢占为 PROCESSING，不做任何改动（否则会顺带延长处理租约）。
     */
    public boolean touchPendingTask(String taskId) {
        String sql = """
                UPDATE moderation_task
                SET updated_at = NOW()
                WHERE task_id = ?
                  AND status = ?
                """;
        return jdbcTemplate.update(sql, taskId, ModerationTaskStatus.PENDING.name()) > 0;
    }

    /**
     * 仅 PENDING 可推进为 FAILED：清扫器重投也失败时的兜底，让任务进入可回放范围。
     * 单独限定 PENDING 而不是复用 markFailed（后者同时允许 PROCESSING），
     * 避免清扫器与"正在被消费者处理"的任务竞态时误杀在途任务。
     */
    public boolean markPendingFailed(String taskId, String errorMessage) {
        String sql = """
                UPDATE moderation_task
                SET status = ?, error_message = ?, updated_at = NOW()
                WHERE task_id = ?
                  AND status = ?
                """;
        return jdbcTemplate.update(sql,
                ModerationTaskStatus.FAILED.name(),
                truncate(errorMessage),
                taskId,
                ModerationTaskStatus.PENDING.name()) > 0;
    }

    public Optional<ModerationTaskRecord> findByTaskId(String taskId) {
        String sql = """
                SELECT task_id, request_id, request_hash, content_type, user_id, content, image_url, image_data,
                       status, decision, violation, confidence, reason, error_message,
                       created_at, updated_at, completed_at
                FROM moderation_task
                WHERE task_id = ?
                """;
        return jdbcTemplate.query(sql, ROW_MAPPER, taskId).stream().findFirst();
    }

    public Optional<ModerationTaskRecord> findLatestReusableByRequestHash(String requestHash) {
        String sql = """
                SELECT task_id, request_id, request_hash, content_type, user_id, content, image_url, image_data,
                       status, decision, violation, confidence, reason, error_message,
                       created_at, updated_at, completed_at
                FROM moderation_task
                -- 去重范围 = 新鲜的 PENDING + 进行中(PROCESSING) + 已完成(COMPLETED)：
                --   命中进行中任务 → 复用 taskId 不再重复投递；
                --   命中已完成任务 → 直接复用历史审核结果。
                -- FAILED 不纳入：失败任务应由回放接口重新入队，不能被自动复用。
                -- PENDING 只认"未超龄"的：落库后宕机/从未入队的 PENDING 孤儿会一直停留在此状态，
                --   若把它当成进行中复用，后续相同请求都会被导向一个永远完不成的 taskId（去重污染）。
                --   超龄 PENDING 交给定时清扫器重新入队，这里主动排除，让新请求走正常入队链路。
                -- 按 created_at 倒序取最新，进行中的新任务优先于旧的已完成任务，避免返回陈旧结果。
                WHERE request_hash = ?
                  AND (
                      (status = ? AND created_at >= ?)
                      OR status = ?
                      OR status = ?
                  )
                ORDER BY created_at DESC
                LIMIT 1
                """;
        return jdbcTemplate.query(
                        sql,
                        ROW_MAPPER,
                        requestHash,
                        ModerationTaskStatus.PENDING.name(),
                        new Timestamp(System.currentTimeMillis() - asyncProperties.getPendingOrphanThresholdMs()),
                        ModerationTaskStatus.PROCESSING.name(),
                        ModerationTaskStatus.COMPLETED.name())
                .stream()
                .findFirst();
    }

    public List<ModerationTaskRecord> findLatestFailedTasks(int limit) {
        String sql = """
                SELECT task_id, request_id, request_hash, content_type, user_id, content, image_url, image_data,
                       status, decision, violation, confidence, reason, error_message,
                       created_at, updated_at, completed_at
                FROM moderation_task
                -- 回放候选来自业务任务表的 FAILED 状态，而非直接扫描 Kafka DLQ topic。
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """;
        return jdbcTemplate.query(
                sql,
                ROW_MAPPER,
                ModerationTaskStatus.FAILED.name(),
                limit);
    }

    private static String truncate(String message) {
        if (message == null) {
            return null;
        }
        return message.length() <= 500 ? message : message.substring(0, 500);
    }

    private static class ModerationTaskRowMapper implements RowMapper<ModerationTaskRecord> {

        @Override
        public ModerationTaskRecord mapRow(ResultSet rs, int rowNum) throws SQLException {
            ModerationTaskRecord record = new ModerationTaskRecord();
            record.setTaskId(rs.getString("task_id"));
            record.setRequestId(rs.getString("request_id"));
            record.setRequestHash(rs.getString("request_hash"));
            record.setContentType(rs.getString("content_type"));
            record.setUserId(rs.getString("user_id"));
            record.setContent(rs.getString("content"));
            record.setImageUrl(rs.getString("image_url"));
            record.setImageData(rs.getString("image_data"));
            record.setStatus(ModerationTaskStatus.valueOf(rs.getString("status")));
            record.setDecision(rs.getString("decision"));
            record.setViolation((Boolean) rs.getObject("violation"));
            record.setConfidence((Double) rs.getObject("confidence"));
            record.setReason(rs.getString("reason"));
            record.setErrorMessage(rs.getString("error_message"));
            record.setCreatedAt(toLocalDateTime(rs.getObject("created_at")));
            record.setUpdatedAt(toLocalDateTime(rs.getObject("updated_at")));
            record.setCompletedAt(toLocalDateTime(rs.getObject("completed_at")));
            return record;
        }

        private LocalDateTime toLocalDateTime(Object value) {
            if (value == null) {
                return null;
            }
            if (value instanceof Timestamp timestamp) {
                return timestamp.toLocalDateTime();
            }
            if (value instanceof LocalDateTime localDateTime) {
                return localDateTime;
            }
            return null;
        }
    }
}
