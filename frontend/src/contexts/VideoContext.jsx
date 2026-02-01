import { createContext, useContext, useState, useCallback } from 'react';

const VideoContext = createContext(null);

/**
 * 원본 비디오 파일을 페이지 간에 공유하기 위한 Provider
 * - Home에서 동영상 선택 시 저장
 * - Result에서 병합 시 사용
 */
export function VideoProvider({ children }) {
    const [originalVideo, setOriginalVideo] = useState(null);
    const [videoUrl, setVideoUrl] = useState(null);

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
        } else {
            setVideoUrl(null);
        }
    }, [videoUrl]);

    // 비디오 정보 초기화
    const clearVideo = useCallback(() => {
        if (videoUrl) {
            URL.revokeObjectURL(videoUrl);
        }
        setOriginalVideo(null);
        setVideoUrl(null);
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
