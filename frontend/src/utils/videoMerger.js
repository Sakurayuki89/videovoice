import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile, toBlobURL } from '@ffmpeg/util';

let ffmpeg = null;
let loaded = false;

/**
 * FFmpeg.wasm 초기화 (싱글톤)
 * @param {function} onProgress - 진행 콜백
 * @returns {Promise<FFmpeg>}
 */
export async function initFFmpeg(onProgress = null) {
    if (loaded && ffmpeg) {
        // 기존 인스턴스에 새 진행 콜백 등록
        if (onProgress) {
            ffmpeg.on('progress', ({ progress }) => {
                onProgress(Math.round(progress * 100));
            });
        }
        return ffmpeg;
    }

    ffmpeg = new FFmpeg();

    if (onProgress) {
        ffmpeg.on('progress', ({ progress }) => {
            onProgress(Math.round(progress * 100));
        });
    }

    // CDN에서 FFmpeg core 로드
    const baseURL = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm';

    await ffmpeg.load({
        coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
        wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm'),
    });

    loaded = true;
    return ffmpeg;
}

/**
 * 원본 비디오에 새 오디오 트랙을 병합
 * @param {File|Blob} videoFile - 원본 비디오 파일
 * @param {Blob|ArrayBuffer} audioData - 새 오디오 데이터 (WAV/MP3)
 * @param {function} onProgress - 진행 콜백 (0-100)
 * @param {function} onStatus - 상태 메시지 콜백
 * @returns {Promise<Blob>} 병합된 비디오 Blob
 */
export async function mergeVideoWithAudio(videoFile, audioData, onProgress = null, onStatus = null) {
    // 1. FFmpeg 초기화
    if (onStatus) onStatus('FFmpeg 로딩 중...');
    const ff = await initFFmpeg(onProgress);

    // 2. 입력 파일명 결정
    const videoExt = getExtension(videoFile.name || 'video.mp4');
    const inputVideo = `input${videoExt}`;
    const inputAudio = 'input_audio.wav';
    const outputFile = 'output.mp4';

    try {
        // 3. 파일 쓰기
        if (onStatus) onStatus('파일 준비 중...');
        await ff.writeFile(inputVideo, await fetchFile(videoFile));

        // audioData가 Blob이면 fetchFile, ArrayBuffer면 Uint8Array로 변환
        if (audioData instanceof Blob) {
            await ff.writeFile(inputAudio, await fetchFile(audioData));
        } else if (audioData instanceof ArrayBuffer) {
            await ff.writeFile(inputAudio, new Uint8Array(audioData));
        } else {
            await ff.writeFile(inputAudio, audioData);
        }

        // 4. 병합 실행
        if (onStatus) onStatus('비디오 병합 중...');

        await ff.exec([
            '-i', inputVideo,
            '-i', inputAudio,
            '-c:v', 'copy',        // 비디오 재인코딩 없이 복사 (빠름)
            '-c:a', 'aac',         // 오디오는 AAC로 인코딩
            '-b:a', '192k',        // 오디오 비트레이트
            '-map', '0:v:0',       // 원본 비디오 스트림만
            '-map', '1:a:0',       // 새 오디오 스트림만
            '-shortest',           // 짧은 쪽에 맞춤
            '-movflags', '+faststart', // 웹 스트리밍 최적화
            outputFile
        ]);

        // 5. 결과 읽기
        if (onStatus) onStatus('완료!');
        const data = await ff.readFile(outputFile);

        // 6. 정리
        await ff.deleteFile(inputVideo);
        await ff.deleteFile(inputAudio);
        await ff.deleteFile(outputFile);

        // 7. Blob 반환
        return new Blob([data.buffer], { type: 'video/mp4' });

    } catch (error) {
        console.error('Video merge failed:', error);

        // 실패해도 파일 정리 시도
        try {
            await ff.deleteFile(inputVideo);
            await ff.deleteFile(inputAudio);
            await ff.deleteFile(outputFile);
        } catch (e) {
            // 정리 실패는 무시
        }

        throw new Error(`비디오 병합 실패: ${error.message}`);
    }
}

/**
 * URL에서 오디오 데이터 다운로드
 * @param {string} url - 오디오 파일 URL
 * @returns {Promise<Blob>}
 */
export async function downloadAudio(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`오디오 다운로드 실패: ${response.status}`);
    }
    return await response.blob();
}

/**
 * Blob을 파일로 다운로드
 * @param {Blob} blob - 다운로드할 Blob
 * @param {string} filename - 저장할 파일명
 */
export function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * 파일 확장자 추출
 * @param {string} filename
 * @returns {string}
 */
function getExtension(filename) {
    const match = filename.match(/\.[^/.]+$/);
    return match ? match[0].toLowerCase() : '.mp4';
}

/**
 * FFmpeg 인스턴스 정리
 */
export function terminateFFmpeg() {
    if (ffmpeg) {
        ffmpeg.terminate();
        ffmpeg = null;
        loaded = false;
    }
}
