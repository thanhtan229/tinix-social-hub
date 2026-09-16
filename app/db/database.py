from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        platform TEXT NOT NULL,
        profile_key TEXT NOT NULL UNIQUE,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        account_id TEXT,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        scheduled_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        error TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_status_schedule ON jobs(status, scheduled_at, created_at);
    CREATE INDEX IF NOT EXISTS idx_jobs_account_status ON jobs(account_id, status);
    """),
    (2, """
    ALTER TABLE accounts ADD COLUMN login_status TEXT NOT NULL DEFAULT 'unknown';
    ALTER TABLE accounts ADD COLUMN last_login_check_at TEXT;
    ALTER TABLE accounts ADD COLUMN disabled_reason TEXT;
    CREATE TABLE chrome_profiles (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL UNIQUE,
        profile_key TEXT NOT NULL UNIQUE,
        remote_port INTEGER,
        last_pid INTEGER,
        last_started_at TEXT,
        last_seen_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
    );
    INSERT INTO chrome_profiles(id,account_id,profile_key,created_at,updated_at)
        SELECT 'profile-' || id,id,profile_key,created_at,updated_at FROM accounts;
    CREATE TABLE publishing_targets (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        target_type TEXT NOT NULL,
        external_id TEXT NOT NULL,
        name TEXT NOT NULL,
        url TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        access_status TEXT NOT NULL DEFAULT 'unknown',
        can_publish INTEGER,
        last_synced_at TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        UNIQUE(account_id,platform,external_id)
    );
    CREATE INDEX idx_targets_account_enabled ON publishing_targets(account_id,enabled,name);
    CREATE TABLE target_groups (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE target_group_members (
        group_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(group_id,target_id),
        FOREIGN KEY(group_id) REFERENCES target_groups(id) ON DELETE CASCADE,
        FOREIGN KEY(target_id) REFERENCES publishing_targets(id) ON DELETE CASCADE
    );
    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """),
    (3, """
    CREATE TABLE brand_profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        products_services TEXT,
        target_audience TEXT,
        tone TEXT,
        pronouns TEXT,
        preferred_keywords_json TEXT NOT NULL DEFAULT '[]',
        forbidden_keywords_json TEXT NOT NULL DEFAULT '[]',
        sample_ctas_json TEXT NOT NULL DEFAULT '[]',
        website TEXT,
        contact_info TEXT,
        hashtag_rules TEXT,
        good_examples_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE prompt_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        operation TEXT NOT NULL,
        system_prompt TEXT NOT NULL,
        user_template TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE content_briefs (
        id TEXT PRIMARY KEY,
        brand_profile_id TEXT,
        title TEXT NOT NULL,
        brief_text TEXT NOT NULL,
        platforms_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(brand_profile_id) REFERENCES brand_profiles(id) ON DELETE SET NULL
    );
    CREATE TABLE content_items (
        id TEXT PRIMARY KEY,
        brand_profile_id TEXT,
        brief_id TEXT,
        title TEXT NOT NULL,
        topic TEXT,
        summary TEXT,
        caption TEXT NOT NULL DEFAULT '',
        hashtags_json TEXT NOT NULL DEFAULT '[]',
        cta TEXT,
        approval_status TEXT NOT NULL DEFAULT 'draft',
        current_revision INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(brand_profile_id) REFERENCES brand_profiles(id) ON DELETE SET NULL,
        FOREIGN KEY(brief_id) REFERENCES content_briefs(id) ON DELETE SET NULL
    );
    CREATE INDEX idx_content_status_updated ON content_items(approval_status,updated_at DESC);
    CREATE TABLE content_media (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        media_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        thumbnail_relative_path TEXT,
        original_name TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        UNIQUE(content_id,relative_path)
    );
    CREATE INDEX idx_content_media_order ON content_media(content_id,sort_order);
    CREATE TABLE platform_content_variants (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        caption TEXT NOT NULL DEFAULT '',
        hashtags_json TEXT NOT NULL DEFAULT '[]',
        cta TEXT,
        title TEXT,
        pinned_comment TEXT,
        video_hook TEXT,
        video_script TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        UNIQUE(content_id,platform)
    );
    CREATE TABLE content_revisions (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        revision_number INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'user',
        note TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        UNIQUE(content_id,revision_number)
    );
    CREATE TABLE content_approvals (
        id TEXT PRIMARY KEY,
        content_id TEXT NOT NULL,
        revision_id TEXT NOT NULL,
        status TEXT NOT NULL,
        note TEXT,
        requested_at TEXT NOT NULL,
        decided_at TEXT,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE CASCADE,
        FOREIGN KEY(revision_id) REFERENCES content_revisions(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_approvals_content_status ON content_approvals(content_id,status,requested_at DESC);
    CREATE TABLE ai_generations (
        id TEXT PRIMARY KEY,
        brief_id TEXT,
        brand_profile_id TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        operation TEXT NOT NULL,
        request_json TEXT NOT NULL,
        response_json TEXT,
        status TEXT NOT NULL,
        error_code TEXT,
        error_message TEXT,
        latency_ms INTEGER,
        created_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY(brief_id) REFERENCES content_briefs(id) ON DELETE SET NULL,
        FOREIGN KEY(brand_profile_id) REFERENCES brand_profiles(id) ON DELETE SET NULL
    );
    CREATE TABLE ai_usage (
        id TEXT PRIMARY KEY,
        generation_id TEXT NOT NULL UNIQUE,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        total_tokens INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(generation_id) REFERENCES ai_generations(id) ON DELETE CASCADE
    );
    """),
    (4, """
    CREATE TABLE jobs_v4 (
        id TEXT PRIMARY KEY,
        account_id TEXT,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        content_id TEXT,
        target_id TEXT,
        approval_id TEXT,
        scheduled_at TEXT,
        next_attempt_at TEXT,
        priority INTEGER NOT NULL DEFAULT 100,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        idempotency_key TEXT,
        dry_run INTEGER NOT NULL DEFAULT 1,
        missed_policy TEXT NOT NULL DEFAULT 'confirm',
        error TEXT,
        failure_code TEXT,
        result_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        commit_reached_at TEXT,
        locked_at TEXT,
        lease_expires_at TEXT,
        correlation_id TEXT,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE RESTRICT,
        FOREIGN KEY(target_id) REFERENCES publishing_targets(id) ON DELETE RESTRICT,
        FOREIGN KEY(approval_id) REFERENCES content_approvals(id) ON DELETE RESTRICT
    );
    INSERT INTO jobs_v4(
        id,account_id,kind,status,payload_json,scheduled_at,attempts,max_attempts,error,
        result_json,created_at,updated_at,started_at,finished_at,cancel_requested,dry_run
    ) SELECT
        id,account_id,kind,
        CASE status WHEN 'failed' THEN 'permanent_failure' WHEN 'running' THEN 'queued' WHEN 'waiting_user' THEN 'checkpoint' ELSE status END,
        payload_json,scheduled_at,attempts,max_attempts,error,result_json,created_at,updated_at,
        CASE WHEN status='running' THEN NULL ELSE started_at END,finished_at,cancel_requested,
        CASE WHEN kind='publish' THEN 1 ELSE 0 END
    FROM jobs;
    DROP TABLE jobs;
    ALTER TABLE jobs_v4 RENAME TO jobs;
    CREATE INDEX idx_jobs_status_due ON jobs(status,next_attempt_at,scheduled_at,priority,created_at);
    CREATE INDEX idx_jobs_account_status ON jobs(account_id,status);
    CREATE INDEX idx_jobs_target_schedule ON jobs(target_id,scheduled_at);
    CREATE UNIQUE INDEX idx_jobs_idempotency ON jobs(idempotency_key) WHERE idempotency_key IS NOT NULL;
    CREATE UNIQUE INDEX idx_jobs_no_duplicate_active_publish
        ON jobs(content_id,target_id,scheduled_at)
        WHERE kind='publish' AND dry_run=0 AND status NOT IN ('succeeded','permanent_failure','cancelled');
    CREATE TABLE publish_job_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_job_events_job_created ON publish_job_events(job_id,created_at);
    CREATE TABLE publish_attempts (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        outcome TEXT,
        failure_code TEXT,
        error_message TEXT,
        result_json TEXT,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        UNIQUE(job_id,attempt_number)
    );
    CREATE TABLE browser_error_artifacts (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        attempt_id TEXT,
        artifact_type TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        FOREIGN KEY(attempt_id) REFERENCES publish_attempts(id) ON DELETE SET NULL
    );
    """),
    (5, """
    CREATE TABLE publication_plans (
        id TEXT PRIMARY KEY,
        content_id TEXT,
        content_revision_id TEXT,
        approval_id TEXT,
        status TEXT NOT NULL,
        dry_run INTEGER NOT NULL DEFAULT 1,
        scheduled_at TEXT,
        missed_policy TEXT NOT NULL DEFAULT 'confirm',
        idempotency_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE RESTRICT,
        FOREIGN KEY(content_revision_id) REFERENCES content_revisions(id) ON DELETE RESTRICT,
        FOREIGN KEY(approval_id) REFERENCES content_approvals(id) ON DELETE RESTRICT
    );
    CREATE INDEX idx_publication_plans_schedule ON publication_plans(status,scheduled_at,created_at);
    CREATE TABLE publication_releases (
        id TEXT PRIMARY KEY,
        plan_id TEXT NOT NULL,
        content_id TEXT,
        content_revision_id TEXT,
        account_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        content_format TEXT NOT NULL DEFAULT 'post',
        status TEXT NOT NULL,
        scheduled_at TEXT,
        settings_json TEXT NOT NULL DEFAULT '{}',
        payload_snapshot_json TEXT NOT NULL DEFAULT '{}',
        media_snapshot_json TEXT NOT NULL DEFAULT '[]',
        selector_version TEXT,
        idempotency_key TEXT NOT NULL UNIQUE,
        job_id TEXT UNIQUE,
        pending_data_json TEXT,
        external_release_id TEXT,
        external_url TEXT,
        verification_method TEXT,
        published_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(plan_id) REFERENCES publication_plans(id) ON DELETE CASCADE,
        FOREIGN KEY(content_id) REFERENCES content_items(id) ON DELETE RESTRICT,
        FOREIGN KEY(content_revision_id) REFERENCES content_revisions(id) ON DELETE RESTRICT,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
        FOREIGN KEY(target_id) REFERENCES publishing_targets(id) ON DELETE RESTRICT,
        FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
    );
    CREATE INDEX idx_publication_releases_range ON publication_releases(scheduled_at,status,platform);
    CREATE INDEX idx_publication_releases_plan ON publication_releases(plan_id,created_at);
    ALTER TABLE jobs ADD COLUMN publication_release_id TEXT REFERENCES publication_releases(id) ON DELETE SET NULL;
    CREATE UNIQUE INDEX idx_jobs_publication_release ON jobs(publication_release_id) WHERE publication_release_id IS NOT NULL;
    INSERT INTO publication_plans(
        id,content_id,approval_id,status,dry_run,scheduled_at,missed_policy,idempotency_key,created_at,updated_at
    ) SELECT
        'legacy-plan-' || id,content_id,approval_id,status,dry_run,scheduled_at,missed_policy,
        'legacy-plan-' || id,created_at,updated_at
    FROM jobs WHERE kind='publish' AND account_id IS NOT NULL AND target_id IS NOT NULL;
    INSERT INTO publication_releases(
        id,plan_id,content_id,account_id,target_id,platform,status,scheduled_at,payload_snapshot_json,
        idempotency_key,job_id,external_url,published_at,created_at,updated_at
    ) SELECT
        'legacy-release-' || j.id,'legacy-plan-' || j.id,j.content_id,j.account_id,j.target_id,a.platform,
        j.status,j.scheduled_at,j.payload_json,'legacy-release-' || j.id,j.id,
        json_extract(j.result_json,'$.post_url'),j.finished_at,j.created_at,j.updated_at
    FROM jobs j JOIN accounts a ON a.id=j.account_id
    WHERE j.kind='publish' AND j.account_id IS NOT NULL AND j.target_id IS NOT NULL;
    UPDATE jobs SET publication_release_id='legacy-release-' || id
    WHERE kind='publish' AND account_id IS NOT NULL AND target_id IS NOT NULL;
    """),
    (6, """
    ALTER TABLE publication_plans ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Asia/Bangkok';
    ALTER TABLE publication_releases ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Asia/Bangkok';
    ALTER TABLE publication_releases ADD COLUMN rescheduled_at TEXT;
    CREATE TABLE channel_posting_slots (
        id TEXT PRIMARY KEY,
        target_id TEXT NOT NULL,
        weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
        minute_of_day INTEGER NOT NULL CHECK(minute_of_day BETWEEN 0 AND 1439),
        timezone TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(target_id) REFERENCES publishing_targets(id) ON DELETE CASCADE,
        UNIQUE(target_id,weekday,minute_of_day)
    );
    CREATE INDEX idx_posting_slots_target ON channel_posting_slots(target_id,enabled,weekday,minute_of_day);
    CREATE TABLE publication_release_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        release_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT,
        message TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(release_id) REFERENCES publication_releases(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_release_events_release ON publication_release_events(release_id,created_at);
    """),
    (7, """
    ALTER TABLE publication_releases ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'pending';
    ALTER TABLE publication_releases ADD COLUMN verified_at TEXT;
    ALTER TABLE publication_releases ADD COLUMN verification_note TEXT;
    CREATE TABLE notifications (
        id TEXT PRIMARY KEY,
        notification_type TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'info',
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        dedupe_key TEXT UNIQUE,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        read_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_notifications_unread ON notifications(read_at,created_at DESC);
    """),
    (8, """
    CREATE TABLE media_assets (
        id TEXT PRIMARY KEY,
        media_type TEXT NOT NULL,
        relative_path TEXT NOT NULL UNIQUE,
        thumbnail_relative_path TEXT,
        original_name TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL UNIQUE,
        width INTEGER,
        height INTEGER,
        duration_seconds REAL,
        alt_text TEXT,
        thumbnail_timestamp REAL,
        source TEXT NOT NULL DEFAULT 'upload',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE media_asset_tags (
        asset_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(asset_id,tag),
        FOREIGN KEY(asset_id) REFERENCES media_assets(id) ON DELETE CASCADE
    );
    ALTER TABLE content_media ADD COLUMN asset_id TEXT REFERENCES media_assets(id) ON DELETE RESTRICT;
    ALTER TABLE content_media ADD COLUMN alt_text TEXT;
    ALTER TABLE content_media ADD COLUMN thumbnail_timestamp REAL;
    INSERT OR IGNORE INTO media_assets(
        id,media_type,relative_path,thumbnail_relative_path,original_name,mime_type,size_bytes,sha256,source,created_at,updated_at
    ) SELECT id,media_type,relative_path,thumbnail_relative_path,original_name,mime_type,size_bytes,sha256,'legacy',created_at,created_at FROM content_media;
    UPDATE content_media SET asset_id=(SELECT id FROM media_assets WHERE media_assets.sha256=content_media.sha256);
    CREATE INDEX idx_content_media_asset ON content_media(asset_id,content_id);
    CREATE INDEX idx_media_assets_type_created ON media_assets(media_type,created_at DESC);
    """),
    (9, """
    CREATE TABLE release_metrics (
        id TEXT PRIMARY KEY,
        release_id TEXT NOT NULL,
        metric_key TEXT NOT NULL,
        metric_date TEXT NOT NULL,
        timezone TEXT NOT NULL,
        value REAL NOT NULL,
        source TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(release_id) REFERENCES publication_releases(id) ON DELETE CASCADE,
        UNIQUE(release_id,metric_key,metric_date,source)
    );
    CREATE INDEX idx_release_metrics_range ON release_metrics(metric_date,metric_key,release_id);
    CREATE TABLE analytics_fetch_runs (
        id TEXT PRIMARY KEY,
        release_id TEXT NOT NULL,
        status TEXT NOT NULL,
        source TEXT NOT NULL,
        metrics_count INTEGER NOT NULL DEFAULT 0,
        message TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY(release_id) REFERENCES publication_releases(id) ON DELETE CASCADE
    );
    """),
    (10, """
    CREATE TABLE api_tokens (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        token_hash TEXT NOT NULL UNIQUE,
        scopes_json TEXT NOT NULL,
        last_used_at TEXT,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    );
    CREATE TABLE webhook_subscriptions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        secret_protected TEXT NOT NULL,
        events_json TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE webhook_outbox (
        id TEXT PRIMARY KEY,
        subscription_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        sent_at TEXT,
        FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_webhook_outbox_due ON webhook_outbox(status,next_attempt_at,created_at);
    """),
    (11, """
    ALTER TABLE accounts ADD COLUMN profile_operation_locked INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE chrome_profile_operations (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        status TEXT NOT NULL,
        source_path TEXT,
        destination_path TEXT,
        backup_name TEXT,
        files_copied INTEGER NOT NULL DEFAULT 0,
        bytes_copied INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_profile_operations_account_created
        ON chrome_profile_operations(account_id,created_at DESC);
    """),
    (12, """
    ALTER TABLE accounts ADD COLUMN username TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN email TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN password TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN secret_2fa TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN email_pass TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN cookie TEXT NOT NULL DEFAULT '';
    """),
    (13, """
    ALTER TABLE accounts ADD COLUMN routing_preference TEXT NOT NULL DEFAULT 'chrome_preferred';
    CREATE TABLE account_connections (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        transport TEXT NOT NULL,
        provider TEXT NOT NULL,
        external_account_id TEXT,
        status TEXT NOT NULL DEFAULT 'disconnected',
        scopes_json TEXT NOT NULL DEFAULT '[]',
        access_token_protected TEXT,
        refresh_token_protected TEXT,
        expires_at TEXT,
        refresh_metadata_json TEXT NOT NULL DEFAULT '{}',
        granted_at TEXT,
        last_validated_at TEXT,
        last_error_code TEXT,
        last_error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        UNIQUE(account_id,transport,provider)
    );
    CREATE INDEX idx_account_connections_status ON account_connections(account_id,transport,status);
    CREATE TABLE oauth_states (
        id TEXT PRIMARY KEY,
        state_hash TEXT NOT NULL UNIQUE,
        account_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        pkce_verifier_protected TEXT,
        redirect_uri TEXT,
        expires_at TEXT NOT NULL,
        consumed_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
    );
    CREATE INDEX idx_oauth_states_expiry ON oauth_states(expires_at,consumed_at);
    ALTER TABLE publication_releases ADD COLUMN requested_routing_policy TEXT NOT NULL DEFAULT 'chrome_preferred';
    ALTER TABLE publication_releases ADD COLUMN publication_transport TEXT;
    ALTER TABLE publication_releases ADD COLUMN provider TEXT;
    ALTER TABLE publication_releases ADD COLUMN provider_version TEXT;
    ALTER TABLE publication_releases ADD COLUMN routing_reason TEXT;
    ALTER TABLE publication_releases ADD COLUMN connection_id TEXT REFERENCES account_connections(id) ON DELETE SET NULL;
    ALTER TABLE publish_attempts ADD COLUMN transport TEXT;
    ALTER TABLE publish_attempts ADD COLUMN provider TEXT;
    ALTER TABLE publish_attempts ADD COLUMN provider_request_id TEXT;
    ALTER TABLE publish_attempts ADD COLUMN commit_possible INTEGER NOT NULL DEFAULT 0;
    """),
    (14, """
    ALTER TABLE accounts ADD COLUMN recovery_email TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN recovery_codes TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN notes TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN starred INTEGER NOT NULL DEFAULT 0;
    """),
    (15, """
    CREATE TABLE ai_provider_configs (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        name TEXT NOT NULL,
        base_url TEXT NOT NULL,
        api_key_protected TEXT NOT NULL,
        key_hint TEXT NOT NULL DEFAULT '',
        text_model TEXT NOT NULL DEFAULT '',
        image_model TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_test_status TEXT NOT NULL DEFAULT 'untested',
        last_test_at TEXT,
        last_error_code TEXT,
        last_error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(provider,name)
    );
    CREATE TABLE ai_provider_models (
        config_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        capabilities_json TEXT NOT NULL DEFAULT '[]',
        raw_metadata_json TEXT NOT NULL DEFAULT '{}',
        fetched_at TEXT NOT NULL,
        PRIMARY KEY(config_id,model_id),
        FOREIGN KEY(config_id) REFERENCES ai_provider_configs(id) ON DELETE CASCADE
    );
    CREATE TABLE platform_apps (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        name TEXT NOT NULL,
        client_id TEXT NOT NULL,
        client_secret_protected TEXT NOT NULL,
        secret_hint TEXT NOT NULL DEFAULT '',
        redirect_uri TEXT NOT NULL,
        api_version TEXT NOT NULL DEFAULT '',
        scopes_json TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_test_status TEXT NOT NULL DEFAULT 'untested',
        last_test_at TEXT,
        last_error_code TEXT,
        last_error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(provider,name)
    );
    ALTER TABLE account_connections ADD COLUMN platform_app_id TEXT REFERENCES platform_apps(id) ON DELETE SET NULL;
    ALTER TABLE oauth_states ADD COLUMN platform_app_id TEXT REFERENCES platform_apps(id) ON DELETE SET NULL;
    CREATE INDEX idx_account_connections_platform_app ON account_connections(platform_app_id);
    """),
    (16, """
    INSERT OR IGNORE INTO prompt_templates(id,name,operation,system_prompt,user_template,enabled,created_at,updated_at) VALUES
    ('system-write','Viết bài mới','write','Tạo một bài viết mới hoàn chỉnh từ brief và ảnh tham chiếu. Bám sát dữ kiện được cung cấp, nêu lợi ích rõ ràng, không tự bịa cam kết hoặc số liệu.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-rewrite','Viết lại','rewrite','Viết lại nội dung từ brief theo cách diễn đạt mới. Giữ nguyên ý chính, dữ kiện, mục tiêu và giọng thương hiệu, đồng thời cải thiện độ rõ ràng và sức thuyết phục.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-shorten','Rút gọn','shorten','Rút gọn nội dung trong brief thành phiên bản súc tích, dễ đọc. Giữ lại thông tin thiết yếu, thông điệp chính và CTA phù hợp.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-expand','Mở rộng','expand','Mở rộng brief thành nội dung giàu ngữ cảnh hơn. Làm rõ lợi ích và điểm khác biệt bằng diễn giải hữu ích, nhưng không thêm dữ kiện chưa được cung cấp.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-hook','Tạo hook','hook','Tập trung tạo phần mở đầu gây chú ý ngay lập tức. Hook phải cụ thể, đúng đối tượng và có thể dùng trong caption hoặc video hook.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-cta','Tạo CTA','cta','Tập trung tạo lời kêu gọi hành động tự nhiên, rõ lợi ích và phù hợp mục tiêu chuyển đổi. Không dùng thúc ép hoặc cam kết sai sự thật.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-hashtags','Tạo hashtag','hashtags','Tập trung đề xuất hashtag liên quan, dễ tìm kiếm và phù hợp từng nền tảng. Kết hợp hashtag thương hiệu, chủ đề và ngách, tránh nhồi nhét.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-variants','Nhiều phiên bản','variants','Tạo một phiên bản chính chất lượng cao và đề xuất các hướng diễn đạt khác biệt về góc tiếp cận, hook hoặc CTA trong phần nội dung phù hợp.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-cross-platform','Chuyển đa nền tảng','cross_platform','Điều chỉnh nội dung riêng cho từng nền tảng được chọn: độ dài, nhịp điệu, định dạng và CTA phải phù hợp hành vi người dùng của nền tảng đó.','ai-studio-context-v1',1,datetime('now'),datetime('now')),
    ('system-video-script','Video script','video_script','Tạo hook và kịch bản video ngắn, rõ nhịp mở đầu, phần triển khai và lời kêu gọi hành động. Dùng brief và ảnh tham chiếu làm ngữ cảnh, không cần video đầu vào.','ai-studio-context-v1',1,datetime('now'),datetime('now'));
    """),
    (17, """
    ALTER TABLE accounts ADD COLUMN password_protected TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN secret_2fa_protected TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN email_pass_protected TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN cookie_protected TEXT NOT NULL DEFAULT '';
    ALTER TABLE accounts ADD COLUMN recovery_codes_protected TEXT NOT NULL DEFAULT '';
    """),
    (18, """
    UPDATE publishing_targets
    SET enabled=0,
        access_status='invalid_discovery',
        last_error='Liên kết điều hướng Facebook, không phải Page có thể đăng.',
        updated_at=datetime('now')
    WHERE platform='facebook' AND external_id IN ('url:latest','url:ad_center');
    """),
]


class Database:
    def __init__(self, path: Path, backup_dir: Path) -> None:
        self.path = path
        self.backup_dir = backup_dir

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        database_existed = self.path.exists() and self.path.stat().st_size > 0
        with self.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            current = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        pending = [(version, sql) for version, sql in MIGRATIONS if version > current]
        if not pending:
            return False
        if database_existed and current > 0:
            self.create_backup(reason=f"pre-migration-v{pending[0][0]}")
        with self.connection() as connection:
            for version, sql in pending:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for statement in sql.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, ?)", (version, utc_now()))
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        integrity = self.integrity_check()
        if not integrity["ok"]:
            raise RuntimeError(f"Database không đạt integrity check sau migration: {integrity['result']}")
        return True

    def ping(self) -> dict[str, Any]:
        try:
            with self.connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return {"ok": True, "result": "ok"}
        except sqlite3.Error as exc:
            return {"ok": False, "result": type(exc).__name__}

    def integrity_check(self) -> dict[str, Any]:
        with self.connection() as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {"ok": result == "ok", "result": result}

    def create_backup(self, reason: str = "manual", keep: int = 7) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = self.backup_dir / f"tinix-{reason}-{stamp}.db"
        with self.connection() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
        backups = sorted(self.backup_dir.glob("tinix-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[keep:]:
            old.unlink(missing_ok=True)
        return destination

    def list_backups(self) -> list[dict[str, Any]]:
        return [
            {"name": p.name, "size": p.stat().st_size, "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()}
            for p in sorted(self.backup_dir.glob("tinix-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
        ]

    def restore_backup(self, name: str) -> Path:
        source = (self.backup_dir / Path(name).name).resolve()
        if source.parent != self.backup_dir.resolve() or not source.is_file():
            raise FileNotFoundError("Không tìm thấy bản backup hợp lệ.")
        with closing(sqlite3.connect(source)) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup bị lỗi integrity check.")
        safety = self.create_backup(reason="before-restore", keep=1000)
        try:
            with closing(sqlite3.connect(source)) as backup, closing(sqlite3.connect(self.path)) as target:
                backup.backup(target)
        except Exception:
            with closing(sqlite3.connect(safety)) as backup, closing(sqlite3.connect(self.path)) as target:
                backup.backup(target)
            raise
        return safety


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in (
        "payload_json", "result_json", "settings_json", "payload_snapshot_json",
        "media_snapshot_json", "pending_data_json",
    ):
        if key in result:
            value = result.pop(key)
            result[key.removesuffix("_json")] = json.loads(value) if value else None
    return result
