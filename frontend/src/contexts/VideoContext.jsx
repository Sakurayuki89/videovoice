import { createContext, useContext, useState, useCallback, useEffect } from 'react';

const VideoContext = createContext(null);

// --- IndexedDB helpers for persisting video across page refreshes ---
const IDB_NAME = 'videovoice';
const IDB_STORE = 'videos';
const IDB_KEY = 'originalVideo';

function openIDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(IDB_NAME, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(IDB_STORE);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function idbSave(file) {
    try {
        const db = await openIDB();
        const tx = db.transaction(IDB_STORE, 'readwrite');
        // Store ArrayBuffer + metadata so we can reconstruct a File
        const buf = await file.arrayBuffer();
        tx.objectStore(IDB_STORE).put(
            { buffer: buf, name: file.name, type: file.type, lastModified: file.lastModified },
            IDB_KEY
        );
        await new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = rej; });
        db.close();
    } catch (e) {
        console.warn('[VideoContext] Failed to save video to IndexedDB:', e);
    }
}

async function idbLoad() {
    try {
        const db = await openIDB();
        const tx = db.transaction(IDB_STORE, 'readonly');
        const req = tx.objectStore(IDB_STORE).get(IDB_KEY);
        const data = await new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = rej; });
        db.close();
        if (data && data.buffer) {
            return new File([data.buffer], data.name, { type: data.type, lastModified: data.lastModified });
        }
    } catch (e) {
        console.warn('[VideoContext] Failed to load video from IndexedDB:', e);
    }
    return null;
}

async function idbClear() {
    try {
        const db = await openIDB();
        const tx = db.transaction(IDB_STORE, 'readwrite');
        tx.objectStore(IDB_STORE).delete(IDB_KEY);
        await new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = rej; });
        db.close();
    } catch (e) {
        console.warn('[VideoContext] Failed to clear IndexedDB:', e);
    }
}

/**
 * 원본 비디오 파일을 페이지 간에 공유하기 위한 Provider
 * - Home에서 동영상 선택 시 저장 (IndexedDB에도 persist)
 * - Result에서 병합 시 사용
 * - 페이지 새로고침 시 IndexedDB에서 복원
 */
export function VideoProvider({ children }) {
    const [originalVideo, setOriginalVideo] = useState(null);
    const [videoUrl, setVideoUrl] = useState(null);

    // Restore from IndexedDB on mount
    useEffect(() => {
        idbLoad().then(file => {
            if (file) {
                console.log('[VideoContext] Restored video from IndexedDB:', file.name);
                setOriginalVideo(file);
                setVideoUrl(URL.createObjectURL(file));
            }
        });
    }, []);

    // 원본 비디오 저장
    const saveOriginalVideo = useCallback((file) => {
        // 이전 URL 해제
        if (videoUrl) {
            URL.revokeObjectURL(videoUrl);
        }

        setOriginalVideo(file);

        // 미리보기용 URL 생성
        if (file) {
            const url = URL.createObjectURL(file);
            setVideoUrl(url);
            // Persist to IndexedDB for refresh survival
            idbSave(file);
        } else {
            setVideoUrl(null);
            idbClear();
        }
    }, [videoUrl]);

    // 비디오 정보 초기화
    const clearVideo = useCallback(() => {
        if (videoUrl) {
            URL.revokeObjectURL(videoUrl);
        }
        setOriginalVideo(null);
        setVideoUrl(null);
        idbClear();
    }, [videoUrl]);

    const value = {
        originalVideo,      // 원본 File 객체
        videoUrl,           // 미리보기용 Blob URL
        saveOriginalVideo,  // 저장 함수
        clearVideo,         // 초기화 함수
        hasVideo: !!originalVideo,
    };

    return (
        <VideoContext.Provider value={value}>
            {children}
        </VideoContext.Provider>
    );
}

export function useVideo() {
    const context = useContext(VideoContext);
    if (!context) {
        throw new Error('useVideo must be used within a VideoProvider');
    }
    return context;
}
