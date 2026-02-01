/**
 * Frontend Configuration
 * These values can be overridden via environment variables (VITE_*)
 */

// API Configuration
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
export const API_BASE = import.meta.env.VITE_API_URL?.replace('/api', '') || 'http://localhost:8000';
export const API_KEY = import.meta.env.VITE_API_KEY || '';

// File Upload Limits
export const MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024; // 2GB
export const ALLOWED_EXTENSIONS = ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.mp3', '.wav', '.flac', '.ogg'];
export const ALLOWED_MIME_TYPES = [
    'video/mp4',
    'video/x-matroska',
    'video/avi',
    'video/quicktime',
    'video/webm',
    'audio/mpeg',
    'audio/wav',
    'audio/x-wav',
    'audio/flac',
    'audio/ogg'
];

// Polling Configuration
export const JOB_POLL_INTERVAL = 2000; // 2 seconds
export const STATUS_POLL_INTERVAL = 30000; // 30 seconds
export const MAX_POLL_RETRIES = 3;

// Timeout Configuration
export const API_TIMEOUT = 30000; // 30 seconds
export const UPLOAD_TIMEOUT = 120000; // 2 minutes

// Job Configuration
export const STALE_JOB_TIMEOUT = 30 * 60 * 1000; // 30 minutes

// Supported Languages
export const LANGUAGES = {
    source: [
        { value: 'auto', label: '자동 감지' },
        { value: 'en', label: '영어' },
        { value: 'ko', label: '한국어' },
        { value: 'ja', label: '일본어' },
        { value: 'zh', label: '중국어' },
        { value: 'es', label: '스페인어' },
        { value: 'fr', label: '프랑스어' },
        { value: 'de', label: '독일어' },
        { value: 'ru', label: '러시아어' },
    ],
    target: [
        { value: 'ko', label: '한국어' },
        { value: 'en', label: '영어' },
        { value: 'ja', label: '일본어' },
        { value: 'zh', label: '중국어' },
        { value: 'es', label: '스페인어' },
        { value: 'fr', label: '프랑스어' },
        { value: 'de', label: '독일어' },
        { value: 'ru', label: '러시아어' },
    ]
};

export default {
    API_URL,
    API_BASE,
    API_KEY,
    MAX_FILE_SIZE,
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    JOB_POLL_INTERVAL,
    STATUS_POLL_INTERVAL,
    MAX_POLL_RETRIES,
    API_TIMEOUT,
    UPLOAD_TIMEOUT,
    STALE_JOB_TIMEOUT,
    LANGUAGES,
};
