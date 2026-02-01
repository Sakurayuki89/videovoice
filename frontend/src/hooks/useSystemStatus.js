import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL?.replace('/api', '') || 'http://localhost:8000';
const POLL_INTERVAL = 30000; // 30 seconds

export function useSystemStatus(autoRefresh = false) {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchStatus = useCallback(async () => {
        try {
            const response = await fetch(`${API_BASE}/api/system/status`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            setStatus(data);
            setError(null);
        } catch (err) {
            console.error('Failed to fetch system status:', err);
            setError(err.message || 'Failed to connect');
            setStatus(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchStatus();

        if (autoRefresh) {
            const intervalId = setInterval(fetchStatus, POLL_INTERVAL);
            return () => clearInterval(intervalId);
        }
    }, [fetchStatus, autoRefresh]);

    return {
        status,
        loading,
        error,
        refresh: fetchStatus,
        isOnline: status?.status === 'online',
    };
}

export default useSystemStatus;
