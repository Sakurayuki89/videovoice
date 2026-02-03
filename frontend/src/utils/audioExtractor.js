import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile, toBlobURL } from '@ffmpeg/util';

let ffmpeg = null;
let loaded = false;

/**
 * FFmpeg.wasm 초기화
 * @param {function} onProgress - 로딩 진행 콜백
 * @returns {Promise<FFmpeg>}
 */
export async function initFFmpeg(onProgress = null) {
    if (loaded && ffmpeg) {
        return ffmpeg;
    }

    ffmpeg = new FFmpeg();

    // 로딩 진행 상태 콜백
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
 * 동영상에서 음성 추출
 * @param {File} videoFile - 입력 동영상 파일
 * @param {function} onProgress - 진행 콜백 (0-100)
 * @param {function} onStatus - 상태 메시지 콜백
 * @returns {Promise<File>} 추출된 MP3 파일
 */
export async function extractAudio(videoFile, onProgress = null, onStatus = null) {
    // Fix: Terminate previous instance to prevent state corruption on second run
    if (ffmpeg && loaded) {
        try {
            ffmpeg.terminate();
        } catch (e) {
            console.warn('FFmpeg terminate warning:', e);
        }
        ffmpeg = null;
        loaded = false;
    }

    // 1. FFmpeg 초기화
    if (onStatus) onStatus('FFmpeg 로딩 중...');
    const ff = await initFFmpeg(onProgress);

    // 2. 입력 파일 쓰기
    if (onStatus) onStatus('파일 준비 중...');
    const inputName = 'input' + getExtension(videoFile.name);
    const outputName = 'output.mp3';

    await ff.writeFile(inputName, await fetchFile(videoFile));

    // 3. 음성 추출 (MP3, 128kbps, mono)
    if (onStatus) onStatus('음성 추출 중...');

    await ff.exec([
        '-i', inputName,
        '-vn',                  // 비디오 제거
        '-acodec', 'libmp3lame', // MP3 코덱
        '-ab', '128k',          // 비트레이트
        '-ar', '44100',         // 샘플레이트
        '-ac', '1',             // 모노
        outputName
    ]);

    // 4. 출력 파일 읽기
    if (onStatus) onStatus('완료!');
    const data = await ff.readFile(outputName);

    // 5. 파일 정리
    try {
        await ff.deleteFile(inputName);
        await ff.deleteFile(outputName);
    } catch (e) {
        console.warn('FFmpeg cleanup warning:', e);
    }

    // 6. File 객체로 변환
    const audioBlob = new Blob([data.buffer], { type: 'audio/mpeg' });
    const audioFile = new File(
        [audioBlob],
        videoFile.name.replace(/\.[^/.]+$/, '.mp3'),
        { type: 'audio/mpeg' }
    );

    return audioFile;
}

/**
 * 파일이 비디오인지 확인
 * @param {File} file
 * @returns {boolean}
 */
export function isVideoFile(file) {
    const videoExtensions = ['.mp4', '.mkv', '.avi', '.mov', '.webm'];
    const ext = getExtension(file.name).toLowerCase();
    return videoExtensions.includes(ext) || file.type.startsWith('video/');
}

/**
 * 파일이 오디오인지 확인
 * @param {File} file
 * @returns {boolean}
 */
export function isAudioFile(file) {
    const audioExtensions = ['.mp3', '.wav', '.flac', '.ogg'];
    const ext = getExtension(file.name).toLowerCase();
    return audioExtensions.includes(ext) || file.type.startsWith('audio/');
}

/**
 * 파일 확장자 추출
 * @param {string} filename
 * @returns {string}
 */
function getExtension(filename) {
    const match = filename.match(/\.[^/.]+$/);
    return match ? match[0] : '';
}

/**
 * FFmpeg 인스턴스 정리 (메모리 해제)
 */
export function terminateFFmpeg() {
    if (ffmpeg) {
        ffmpeg.terminate();
        ffmpeg = null;
        loaded = false;
    }
}
