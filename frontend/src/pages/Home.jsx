import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, Languages, Mic2, ShieldCheck, ArrowRight, Loader2, AlertCircle, Music, CheckCircle2, Film, Clock } from 'lucide-react';
import { createJob } from '../services/api';
import {
    MAX_FILE_SIZE,
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    LANGUAGES
} from '../config';
import { extractAudio, isVideoFile, isAudioFile } from '../utils/audioExtractor';
import { useVideo } from '../contexts/VideoContext';

export default function Home() {
    const navigate = useNavigate();
    const fileInputRef = useRef(null);
    const { saveOriginalVideo } = useVideo();

    const [file, setFile] = useState(null);
    const [previewUrl, setPreviewUrl] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState(null);

    // 음성 추출 상태
    const [extractionState, setExtractionState] = useState({
        isExtracting: false,
        progress: 0,
        status: ''
    });

    // 추출된 오디오 캐시 (중복 추출 방지)
    const [extractedAudio, setExtractedAudio] = useState(null);

    const [settings, setSettings] = useState({
        sourceLang: 'auto',
        targetLang: 'ko',
        cloneVoice: true,
        verifyTranslation: false,
        syncMode: 'optimize'  // 'optimize' = natural translation, 'stretch' = extend video
    });

    // 비디오 미리보기 URL 생성/해제
    useEffect(() => {
        if (file && isVideoFile(file)) {
            const url = URL.createObjectURL(file);
            setPreviewUrl(url);
            return () => URL.revokeObjectURL(url);
        } else {
            setPreviewUrl(null);
        }
    }, [file]);

    const validateFile = (selectedFile) => {
        if (!selectedFile) {
            return '파일이 선택되지 않았습니다';
        }
        if (selectedFile.size > MAX_FILE_SIZE) {
            const sizeMB = Math.round(selectedFile.size / (1024 * 1024));
            const maxMB = Math.round(MAX_FILE_SIZE / (1024 * 1024));
            return `파일이 너무 큽니다 (${sizeMB}MB). 최대 크기: ${maxMB}MB`;
        }
        if (selectedFile.size < 1024) {
            return '파일이 너무 작아 유효한 비디오가 아닙니다.';
        }
        const fileName = selectedFile.name.toLowerCase();
        const hasValidExtension = ALLOWED_EXTENSIONS.some(ext => fileName.endsWith(ext));
        if (!hasValidExtension) {
            return `지원하지 않는 파일 형식입니다. 지원 형식: ${ALLOWED_EXTENSIONS.join(', ')}`;
        }
        if (selectedFile.type && !ALLOWED_MIME_TYPES.includes(selectedFile.type) && !selectedFile.type.startsWith('video/') && !selectedFile.type.startsWith('audio/')) {
            return '지원하지 않는 파일 형식입니다.';
        }
        return null;
    };

    const handleDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setIsDragging(true);
        } else if (e.type === 'dragleave') {
            setIsDragging(false);
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFile(e.dataTransfer.files[0]);
        }
    };

    // 파일 선택만 (자동 추출 안함)
    const handleFile = (selectedFile) => {
        console.log('handleFile called:', selectedFile?.name, selectedFile?.size);
        const validationError = validateFile(selectedFile);
        if (validationError) {
            console.log('Validation error:', validationError);
            setError(validationError);
            setFile(null);
            return;
        }
        console.log('File set successfully.');
        setFile(selectedFile);
        setError(null);

        // 새 파일이면 캐시된 오디오 초기화
        setExtractedAudio(null);
        setExtractionState({ isExtracting: false, progress: 0, status: '' });
    };

    // 음성 추출 시작 (버튼 클릭 시)
    const handleExtractAudio = async () => {
        if (!file) {
            setError("먼저 비디오 파일을 선택해주세요.");
            return;
        }

        // 오디오 파일이면 추출 필요 없음
        if (isAudioFile(file)) {
            setExtractedAudio(file);
            saveOriginalVideo(null);
            return;
        }

        // 이미 추출된 오디오가 있으면 스킵
        if (extractedAudio) {
            console.log('[VideoVoice] Audio already extracted.');
            return;
        }

        setError(null);

        try {
            // 원본 동영상을 Context에 저장 (나중에 병합할 때 사용)
            saveOriginalVideo(file);

            // 대용량 파일 경고
            const isLargeFile = file.size > 500 * 1024 * 1024; // 500MB
            const initialStatus = isLargeFile
                ? '대용량 파일 음성 추출 중... (시간이 걸릴 수 있습니다)'
                : 'FFmpeg 로딩 중...';

            setExtractionState({
                isExtracting: true,
                progress: 0,
                status: initialStatus
            });

            const audio = await extractAudio(
                file,
                (progress) => {
                    setExtractionState(prev => ({ ...prev, progress }));
                },
                (status) => {
                    setExtractionState(prev => ({ ...prev, status }));
                }
            );

            console.log(`Audio extracted: ${audio.name} (${(audio.size / 1024).toFixed(1)} KB)`);

            // 추출된 오디오를 캐시에 저장
            setExtractedAudio(audio);

            setExtractionState({
                isExtracting: false,
                progress: 100,
                status: '음성 추출 완료!'
            });
        } catch (err) {
            console.error('Audio extraction failed:', err);
            setError(`음성 추출 실패: ${err.message}. 더 작은 파일을 사용해 보세요.`);
            setExtractionState({ isExtracting: false, progress: 0, status: '' });
        }
    };

    // 더빙 시작 (업로드 + 파이프라인)
    const handleStartDubbing = async () => {
        if (!file) {
            setError("먼저 비디오 파일을 선택해주세요.");
            return;
        }

        // 비디오인데 추출 안했으면 먼저 추출 요청
        if (isVideoFile(file) && !extractedAudio) {
            setError("먼저 '음성 추출' 버튼을 눌러주세요.");
            return;
        }

        // 항상 원본 파일을 업로드 (서버에서 비디오 병합 가능하도록)
        // extractedAudio는 미리듣기 용도로만 사용
        const fileToUpload = file;

        setIsSubmitting(true);
        setError(null);

        // 서버에 업로드
        const formData = new FormData();
        formData.append('file', fileToUpload);
        formData.append('source_lang', settings.sourceLang);
        formData.append('target_lang', settings.targetLang);
        formData.append('clone_voice', settings.cloneVoice);
        formData.append('verify_translation', settings.verifyTranslation);
        formData.append('sync_mode', settings.syncMode);

        try {
            console.log('[VideoVoice] Uploading to server...');
            const job = await createJob(formData);
            console.log('[VideoVoice] Job created:', job.job_id);
            console.log('[VideoVoice] Navigating to process page...');
            navigate(`/process/${job.job_id}`);
        } catch (err) {
            console.error('[VideoVoice] Upload failed:', err);
            setError(err.message || "작업 시작에 실패했습니다. 백엔드 서버가 실행 중인지 확인해주세요.");
            setIsSubmitting(false);
        }
    };

    // 버튼 상태 결정
    const canExtract = file && isVideoFile(file) && !extractedAudio && !extractionState.isExtracting;
    const canStartDubbing = file && (extractedAudio || isAudioFile(file)) && !isSubmitting;
    const isExtractionComplete = extractedAudio !== null;

    return (
        <div className="max-w-4xl mx-auto py-12 px-4">
            <div className="text-center mb-12">
                <h1 className="text-5xl font-extrabold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-violet-500">
                    VideoVoice
                </h1>
                <p className="text-xl text-slate-400">
                    AI 기반 로컬 비디오 더빙 시스템
                </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">

                {/* Upload Zone */}
                <div className="md:col-span-2">
                    <div
                        className={`
              glass-panel min-h-[20rem] flex flex-col items-center justify-center p-8 border-2 border-dashed transition-all cursor-pointer
              ${isDragging ? 'border-cyan-400 bg-cyan-500/10' : 'border-slate-700 hover:border-slate-500'}
              ${file ? 'border-solid border-cyan-500/50' : ''}
            `}
                        onDragEnter={handleDrag}
                        onDragLeave={handleDrag}
                        onDragOver={handleDrag}
                        onDrop={handleDrop}
                        onClick={(e) => {
                            if (e.target === fileInputRef.current) return;
                            if (extractionState.isExtracting) return; // 추출 중에는 파일 변경 불가
                            fileInputRef.current?.click();
                        }}
                    >
                        <input
                            type="file"
                            className="hidden"
                            ref={fileInputRef}
                            accept={ALLOWED_EXTENSIONS.join(',')}
                            onClick={(e) => {
                                e.stopPropagation();
                                e.target.value = '';
                            }}
                            onChange={(e) => {
                                const selectedFile = e.target.files?.[0];
                                console.log('File selected:', selectedFile?.name);
                                if (selectedFile) {
                                    handleFile(selectedFile);
                                }
                            }}
                        />

                        {extractionState.isExtracting ? (
                            <div className="text-center w-full">
                                <div className="w-20 h-20 bg-gradient-to-br from-cyan-500/20 to-violet-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                                    <Music className="w-10 h-10 text-cyan-400 animate-pulse" />
                                </div>
                                <p className="text-lg text-white font-medium mb-2">{extractionState.status}</p>
                                <div className="w-64 mx-auto bg-slate-700 rounded-full h-2 mt-4">
                                    <div
                                        className="bg-gradient-to-r from-cyan-500 to-violet-500 h-2 rounded-full transition-all duration-300"
                                        style={{ width: `${extractionState.progress}%` }}
                                    />
                                </div>
                                <p className="text-sm text-slate-400 mt-2">
                                    {extractionState.progress > 0 ? `${extractionState.progress}%` : '잠시만 기다려주세요...'}
                                </p>
                            </div>
                        ) : file ? (
                            <div className="text-center w-full flex flex-col items-center">
                                {previewUrl ? (
                                    <div className="relative w-full max-w-sm rounded-lg overflow-hidden bg-black/50 mb-4 shadow-lg border border-slate-700">
                                        <video
                                            src={previewUrl}
                                            controls
                                            muted
                                            autoPlay={false}
                                            className="w-full max-h-48 object-contain"
                                        />
                                    </div>
                                ) : (
                                    <VideoFileIcon />
                                )}
                                <p className="text-xl font-medium text-white mb-2 truncate max-w-sm">{file.name}</p>
                                <p className="text-sm text-slate-400">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>

                                {/* 추출 상태 표시 */}
                                {isExtractionComplete && (
                                    <div className="flex items-center gap-2 mt-3 text-green-400">
                                        <CheckCircle2 className="w-5 h-5" />
                                        <span className="text-sm">음성 추출 완료 ({(extractedAudio.size / 1024).toFixed(1)} KB)</span>
                                    </div>
                                )}

                                <p className="text-xs text-cyan-400 mt-4">클릭하여 파일 변경</p>
                            </div>
                        ) : (
                            <div className="text-center">
                                <div className="w-20 h-20 bg-slate-800/50 rounded-full flex items-center justify-center mx-auto mb-6">
                                    <Upload className="w-10 h-10 text-slate-400" />
                                </div>
                                <p className="text-lg text-white font-medium mb-2">비디오 또는 오디오를 드래그하세요</p>
                                <p className="text-slate-400 text-sm">또는 클릭하여 파일 선택</p>
                                <p className="text-slate-500 text-xs mt-4">
                                    지원 형식: {ALLOWED_EXTENSIONS.map(e => e.slice(1).toUpperCase()).join(', ')}
                                    {' '}(최대 {Math.round(MAX_FILE_SIZE / (1024 * 1024))}MB)
                                </p>
                            </div>
                        )}
                    </div>
                </div>

                {/* Settings Panel */}
                <div className="glass-panel p-6 flex flex-col justify-between">
                    <div>
                        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                            <Languages className="w-5 h-5 text-cyan-400" />
                            설정
                        </h3>

                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm text-slate-400 mb-1">원본 언어</label>
                                <select
                                    value={settings.sourceLang}
                                    onChange={(e) => setSettings({ ...settings, sourceLang: e.target.value })}
                                    disabled={extractionState.isExtracting || isSubmitting}
                                >
                                    {LANGUAGES.source.map(lang => (
                                        <option key={lang.value} value={lang.value}>{lang.label}</option>
                                    ))}
                                </select>
                            </div>

                            <div>
                                <label className="block text-sm text-slate-400 mb-1">목표 언어</label>
                                <select
                                    value={settings.targetLang}
                                    onChange={(e) => setSettings({ ...settings, targetLang: e.target.value })}
                                    disabled={extractionState.isExtracting || isSubmitting}
                                >
                                    {LANGUAGES.target.map(lang => (
                                        <option key={lang.value} value={lang.value}>{lang.label}</option>
                                    ))}
                                </select>
                            </div>

                            {/* Sync Mode Selection */}
                            <div className="pt-3 border-t border-slate-700">
                                <label className="block text-sm text-slate-400 mb-3">싱크 모드</label>
                                <div className="space-y-2">
                                    <label
                                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                                            settings.syncMode === 'optimize'
                                                ? 'border-cyan-500 bg-cyan-500/10'
                                                : 'border-slate-700 hover:border-slate-600'
                                        }`}
                                    >
                                        <input
                                            type="radio"
                                            name="syncMode"
                                            value="optimize"
                                            checked={settings.syncMode === 'optimize'}
                                            onChange={(e) => setSettings({ ...settings, syncMode: e.target.value })}
                                            disabled={extractionState.isExtracting || isSubmitting}
                                            className="hidden"
                                        />
                                        <div className={`w-4 h-4 mt-0.5 rounded-full border-2 flex items-center justify-center ${
                                            settings.syncMode === 'optimize' ? 'border-cyan-500' : 'border-slate-600'
                                        }`}>
                                            {settings.syncMode === 'optimize' && (
                                                <div className="w-2 h-2 rounded-full bg-cyan-500" />
                                            )}
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex items-center gap-2">
                                                <Film className="w-4 h-4 text-cyan-400" />
                                                <span className="text-sm font-medium text-white">자연스럽게</span>
                                                <span className="text-[10px] px-1.5 py-0.5 bg-cyan-500/20 text-cyan-400 rounded">추천</span>
                                            </div>
                                            <p className="text-xs text-slate-500 mt-1">
                                                번역을 간결하게 줄여서 영상 길이에 맞춤
                                            </p>
                                            <p className="text-[10px] text-slate-600 mt-0.5">
                                                영화, 브이로그, 드라마, 숏폼
                                            </p>
                                        </div>
                                    </label>

                                    <label
                                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                                            settings.syncMode === 'stretch'
                                                ? 'border-violet-500 bg-violet-500/10'
                                                : 'border-slate-700 hover:border-slate-600'
                                        }`}
                                    >
                                        <input
                                            type="radio"
                                            name="syncMode"
                                            value="stretch"
                                            checked={settings.syncMode === 'stretch'}
                                            onChange={(e) => setSettings({ ...settings, syncMode: e.target.value })}
                                            disabled={extractionState.isExtracting || isSubmitting}
                                            className="hidden"
                                        />
                                        <div className={`w-4 h-4 mt-0.5 rounded-full border-2 flex items-center justify-center ${
                                            settings.syncMode === 'stretch' ? 'border-violet-500' : 'border-slate-600'
                                        }`}>
                                            {settings.syncMode === 'stretch' && (
                                                <div className="w-2 h-2 rounded-full bg-violet-500" />
                                            )}
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex items-center gap-2">
                                                <Clock className="w-4 h-4 text-violet-400" />
                                                <span className="text-sm font-medium text-white">내용 전체 전달</span>
                                            </div>
                                            <p className="text-xs text-slate-500 mt-1">
                                                말이 길어지면 영상을 느리게 재생
                                            </p>
                                            <p className="text-[10px] text-slate-600 mt-0.5">
                                                강의, 튜토리얼, 뉴스, 프레젠테이션
                                            </p>
                                        </div>
                                    </label>
                                </div>
                            </div>

                            <div className="pt-2 space-y-3">
                                <label className="flex items-center gap-3 cursor-pointer group">
                                    <div className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${settings.cloneVoice ? 'bg-cyan-500 border-cyan-500' : 'border-slate-600'}`}>
                                        {settings.cloneVoice && <div className="w-2 h-2 bg-white rounded-full" />}
                                    </div>
                                    <input
                                        type="checkbox"
                                        className="hidden"
                                        checked={settings.cloneVoice}
                                        onChange={(e) => setSettings({ ...settings, cloneVoice: e.target.checked })}
                                        disabled={extractionState.isExtracting || isSubmitting}
                                    />
                                    <div className="flex-1">
                                        <span className="text-sm text-white block">음성 복제</span>
                                        <span className="text-xs text-slate-500">화자 음색 유지</span>
                                    </div>
                                    <Mic2 className="w-4 h-4 text-slate-500 group-hover:text-cyan-400 transition-colors" />
                                </label>

                                <label className="flex items-center gap-3 cursor-pointer group">
                                    <div className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${settings.verifyTranslation ? 'bg-violet-500 border-violet-500' : 'border-slate-600'}`}>
                                        {settings.verifyTranslation && <div className="w-2 h-2 bg-white rounded-full" />}
                                    </div>
                                    <input
                                        type="checkbox"
                                        className="hidden"
                                        checked={settings.verifyTranslation}
                                        onChange={(e) => setSettings({ ...settings, verifyTranslation: e.target.checked })}
                                        disabled={extractionState.isExtracting || isSubmitting}
                                    />
                                    <div className="flex-1">
                                        <span className="text-sm text-white block">검증 (Gemini)</span>
                                        <span className="text-xs text-amber-400">외부 API (과금 주의)</span>
                                    </div>
                                    <ShieldCheck className="w-4 h-4 text-slate-500 group-hover:text-violet-400 transition-colors" />
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Error Display */}
            {error && (
                <div className="mt-6 p-6 bg-red-500/20 border-2 border-red-500/50 rounded-xl">
                    <div className="flex items-start gap-4">
                        <div className="p-2 bg-red-500/30 rounded-full">
                            <AlertCircle className="w-6 h-6 text-red-400" />
                        </div>
                        <div className="flex-1">
                            <h3 className="text-lg font-bold text-red-400 mb-2">오류 발생</h3>
                            <p className="text-red-300">{error}</p>
                        </div>
                        <button
                            onClick={() => setError(null)}
                            className="text-red-400 hover:text-red-300 text-lg font-bold px-2"
                        >
                            ✕
                        </button>
                    </div>
                </div>
            )}

            {/* Action Buttons - 분리된 버튼 */}
            <div className="mt-6 flex items-center justify-end gap-4">
                {/* 음성 추출 버튼 (비디오 파일 & 추출 안됨) */}
                {file && isVideoFile(file) && !isExtractionComplete && (
                    <button
                        onClick={handleExtractAudio}
                        disabled={!canExtract}
                        className={`btn-primary text-lg px-8 ${!canExtract ? 'btn-disabled' : ''}`}
                    >
                        {extractionState.isExtracting ? (
                            <>
                                <Loader2 className="w-5 h-5 animate-spin" />
                                추출 중...
                            </>
                        ) : (
                            <>
                                <Music className="w-5 h-5" />
                                음성 추출
                            </>
                        )}
                    </button>
                )}

                {/* 더빙 시작 버튼 (추출 완료 or 오디오 파일) */}
                {(isExtractionComplete || (file && isAudioFile(file))) && (
                    <button
                        onClick={handleStartDubbing}
                        disabled={!canStartDubbing}
                        className={`btn-primary text-lg px-8 ${!canStartDubbing ? 'btn-disabled' : ''}`}
                    >
                        {isSubmitting ? (
                            <>
                                <Loader2 className="w-5 h-5 animate-spin" />
                                업로드 중...
                            </>
                        ) : (
                            <>
                                더빙 시작
                                <ArrowRight className="w-5 h-5" />
                            </>
                        )}
                    </button>
                )}
            </div>

            {/* Limits & Recommendations Info */}
            <div className="mt-12 p-4 bg-slate-800/50 rounded-lg border border-slate-700 backdrop-blur-sm">
                <div className="flex flex-col md:flex-row gap-6 text-sm text-slate-400 justify-center items-center text-center md:text-left">
                    <div className="flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-amber-400" />
                        <span>파일 크기 제한: <strong className="text-slate-300">최대 2GB</strong></span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-1 h-1 bg-slate-600 rounded-full hidden md:block" />
                        <span>권장 영상 길이: <strong className="text-slate-300">1시간 이내</strong></span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-1 h-1 bg-slate-600 rounded-full hidden md:block" />
                        <span>긴 영상은 처리 시간이 오래 걸릴 수 있습니다.</span>
                    </div>
                </div>
            </div>
        </div>
    );
}

function VideoFileIcon() {
    return (
        <svg className="w-16 h-16 mx-auto mb-2 text-cyan-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
            <polyline points="14 2 14 8 20 8" />
            <path d="M10 13l2 2 4-4" />
        </svg>
    );
}
