import axios from 'axios';
import { API_URL, API_KEY, API_BASE, API_TIMEOUT, UPLOAD_TIMEOUT } from '../config';

const api = axios.create({
    baseURL: API_URL,
    timeout: API_TIMEOUT,
});

// Add API key to requests if configured
api.interceptors.request.use((config) => {
    if (API_KEY) {
        config.headers['X-API-Key'] = API_KEY;
    }
    return config;
});

// Global error handler
api.interceptors.response.use(
    (response) => response,
    (error) => {
        // Handle specific error types
        if (error.response) {
            const { status, data } = error.response;

            switch (status) {
                case 400:
                    throw new Error(data.detail || 'Invalid request');
                case 401:
                    throw new Error('Authentication required. Please provide a valid API key.');
                case 403:
                    throw new Error('Access denied. Invalid API key.');
                case 404:
                    throw new Error(data.detail || 'Resource not found');
                case 413:
                    throw new Error(data.detail || 'File too large');
                case 429:
                    throw new Error('Rate limit exceeded. Please wait before trying again.');
                case 500:
                    throw new Error('Server error. Please try again later.');
                default:
                    throw new Error(data.detail || `Request failed with status ${status}`);
            }
        } else if (error.request) {
            throw new Error('Network error. Please check your connection and ensure the backend is running.');
        } else {
            throw new Error(error.message || 'An unexpected error occurred');
        }
    }
);

export const createJob = async (formData) => {
    const response = await api.post('/jobs', formData, {
        headers: {
            'Content-Type': 'multipart/form-data',
        },
        timeout: UPLOAD_TIMEOUT,
    });
    return response.data;
};

export const getJob = async (jobId) => {
    const response = await api.get(`/jobs/${jobId}`);
    return response.data;
};

export const cancelJob = async (jobId) => {
    const response = await api.post(`/jobs/${jobId}/cancel`);
    return response.data;
};

export const getOutputUrl = (outputFile) => {
    // Convert relative path to full URL
    return `${API_BASE}${outputFile}`;
};

export default api;
