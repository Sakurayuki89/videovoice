import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, Languages, Mic2, ShieldCheck, ArrowRight, Loader2, AlertCircle, Music, CheckCircle2, Check, Film, Clock, Gauge, Settings, ChevronDown, ChevronUp } from 'lucide-react';
import { createJob } from '../services/api';
import {
    MAX_FILE_SIZE,
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    LANGUAGES
} from '../config';
import { extractAudio, isVideoFile, isAudioFile } from '../utils/audioExtractor';
import { useVideo } from '../contexts/VideoContext';
import { useSystemStatus } from '../hooks/useSystemStatus';

export default function Home() {
    const navigate = useNavigate();
    const fileInputRef = useRef(null);
    const { saveOriginalVideo } = useVideo();
    const { status: systemStatus } = useSystemStatus();

    const [file, setFile] = useState(null);
    const [previewUrl, setPreviewUrl] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const [showAdvanced, setShowAdvanced] = useState(false);

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
        syncMode: 'speed_audio',  // 'optimize' = natural translation, 'stretch' = extend video
        translationEngine: 'gemini',  // Default to Gemini for best quality
        ttsEngine: 'auto', // 'auto' | 'xtts' | 'edge' | 'silero' | 'elevenlabs' | 'openai'
        sttEngine: 'local' // 'local' | 'groq' | 'openai' - Let backend decide default if 'local', but we'll show selector
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

    // 언어 조합별 추천 설정 맵
    const getRecommendedSettings = (sourceLang, targetLang) => {
        const SYNC_MODE_NAMES = {
            'optimize': '자연스러운 속도',
            'speed_audio': '영상 길이에 맞춤',
            'stretch': '영상 속도 조절'
        };

        // 기본 추천값
        const rec = {
            syncMode: 'speed_audio',
            syncReason: '대부분의 경우 안정적',
            ttsEngine: 'auto',
            ttsReason: '언어에 맞게 자동 선택',
            translationEngine: 'gemini',
            translationReason: '최고 품질 다국어 번역',
            sttEngine: 'local',
            sttReason: 'GPU 로컬 처리',
            cloneVoice: true,
            cloneReason: '원본 음색 유지',
        };

        // 타겟 언어별 TTS 최적화
        const hasElevenLabs = systemStatus?.api_status?.elevenlabs === 'configured';

        if (hasElevenLabs) {
            // ElevenLabs 키가 있으면 최상급 품질 우선
            rec.ttsEngine = 'elevenlabs';
            rec.ttsReason = '최상급 다국어 음성 합성';
            rec.cloneVoice = true;
            rec.cloneReason = 'ElevenLabs 음성 복제 최고 품질';
        } else if (targetLang === 'ko') {
            rec.ttsEngine = 'edge';
            rec.ttsReason = '한국어 Edge TTS 고품질';
            rec.cloneVoice = false;
            rec.cloneReason = 'Edge TTS가 한국어에 자연스러움';
        } else if (targetLang === 'ru') {
            rec.ttsEngine = 'silero';
            rec.ttsReason = '러시아어 특화 Silero 엔진';
            rec.cloneVoice = false;
            rec.cloneReason = 'Silero가 러시아어에 최적화됨';
        } else if (['en', 'ja'].includes(targetLang)) {
            rec.ttsEngine = 'xtts';
            rec.ttsReason = '음성 복제 + 고품질';
            rec.cloneVoice = true;
            rec.cloneReason = 'XTTS 음성 복제 우수';
        } else {
            rec.ttsEngine = 'edge';
            rec.ttsReason = '안정적인 다국어 지원';
            rec.cloneVoice = false;
            rec.cloneReason = 'Edge가 다국어에서 안정적';
        }

        // 소스 언어별 STT 최적화
        if (['ja', 'zh', 'ko'].includes(sourceLang) || sourceLang === 'auto') {
            rec.sttEngine = 'local';
            rec.sttReason = 'Whisper large-v3 최고 정확도';
        } else if (['en', 'ru'].includes(sourceLang)) {
            rec.sttEngine = 'groq';
            rec.sttReason = 'EN/RU 고속 인식';
        }

        // verbose 타겟 언어
        const verboseTargets = ['de', 'fr', 'es', 'it', 'pt', 'ru'];
        const conciseTargets = ['zh', 'ja', 'ko'];

        if (verboseTargets.includes(targetLang)) {
            rec.syncMode = 'speed_audio';
            rec.syncReason = '번역이 길어지기 쉬움';
        } else if (conciseTargets.includes(targetLang) && !conciseTargets.includes(sourceLang)) {
            rec.syncMode = 'speed_audio';
            rec.syncReason = '번역이 짧아질 수 있어 무음 방지';
        }

        rec.syncName = SYNC_MODE_NAMES[rec.syncMode];
        return rec;
    };

    const recommendation = getRecommendedSettings(settings.sourceLang, settings.targetLang);

    // 언어 변경 시 추천 설정 자동 적용
    const prevLangsRef = useRef({ src: settings.sourceLang, tgt: settings.targetLang });
    useEffect(() => {
        const prev = prevLangsRef.current;
        if (prev.src === settings.sourceLang && prev.tgt === settings.targetLang) return;
        prevLangsRef.current = { src: settings.sourceLang, tgt: settings.targetLang };

        const rec = getRecommendedSettings(settings.sourceLang, settings.targetLang);
        setSettings(prev => ({
            ...prev,
            syncMode: rec.syncMode,
            ttsEngine: rec.ttsEngine,
            translationEngine: rec.translationEngine,
            sttEngine: rec.sttEngine,
            cloneVoice: rec.cloneVoice,
        }));
    }, [settings.sourceLang, settings.targetLang]);


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
        const validationError = validateFile(selectedFile);
        if (validationError) {
            setError(validationError);
            setFile(null);
            return;
        }
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

        if (isAudioFile(file)) {
            setExtractedAudio(file);
            saveOriginalVideo(null);
            return;
        }

        if (extractedAudio) return;

        setError(null);

        try {
            saveOriginalVideo(file);
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
                (progress) => setExtractionState(prev => ({ ...prev, progress })),
                (status) => setExtractionState(prev => ({ ...prev, status }))
            );

            setExtractedAudio(audio);
            setExtractionState({
                isExtracting: false,
                progress: 100,
                status: '음성 추출 완료!'
            });
        } catch (err) {
            console.error('Audio extraction failed:', err);
            setError(`음성 추출 실패: ${err.message}.`);
            setExtractionState({ isExtracting: false, progress: 0, status: '' });
        }
    };

    // 더빙 시작
    const handleStartDubbing = async () => {
        if (!file) {
            setError("먼저 비디오 파일을 선택해주세요.");
            return;
        }

        // Save original video for client-side merge on Result page
        if (isVideoFile(file)) {
            saveOriginalVideo(file);
        }

        const fileToUpload = file;
        setIsSubmitting(true);
        setError(null);

        const formData = new FormData();
        formData.append('file', fileToUpload);
        formData.append('source_lang', settings.sourceLang);
        formData.append('target_lang', settings.targetLang);
        formData.append('clone_voice', settings.cloneVoice);
        formData.append('verify_translation', settings.verifyTranslation);
        formData.append('sync_mode', settings.syncMode);
        formData.append('translation_engine', settings.translationEngine);
        formData.append('tts_engine', settings.ttsEngine);
        formData.append('stt_engine', settings.sttEngine);

        try {
            const job = await createJob(formData);
            navigate(`/process/${job.job_id}`);
        } catch (err) {
            console.error('[VideoVoice] Upload failed:', err);
            setError(err.message || "작업 시작에 실패했습니다. 백엔드 서버 상태를 확인해주세요.");
            setIsSubmitting(false);
        }
    };

    const canExtract = file && isVideoFile(file) && !extractedAudio && !extractionState.isExtracting;
    const canStartDubbing = file && !isSubmitting;
    const isExtractionComplete = extractedAudio !== null;

    return (
        <div className="max-w-6xl mx-auto py-12 px-4">
            <div className="text-center mb-12">
                <h1 className="text-5xl font-extrabold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-violet-500 tracking-tight">
                    VideoVoice
                </h1>
                <p className="text-xl text-slate-400 max-w-2xl mx-auto">
                    AI 기반 로컬 비디오 더빙 시스템으로 언어의 장벽을 허무세요.
                </p>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
                {/* Upload Zone (Left side, takes 3 columns) */}
                <div className="lg:col-span-3 space-y-6">
                    <div
                        className={`
                            glass-panel min-h-[400px] flex flex-col items-center justify-center p-8 border-2 border-dashed transition-all duration-300 cursor-pointer relative overflow-hidden group
                            ${isDragging ? 'border-cyan-400 bg-cyan-500/10 scale-[1.02]' : 'border-slate-700 hover:border-cyan-500/50 hover:bg-slate-800/80'}
                            ${file ? 'border-solid border-cyan-500/30' : ''}
                        `}
                        onDragEnter={handleDrag}
                        onDragLeave={handleDrag}
                        onDragOver={handleDrag}
                        onDrop={handleDrop}
                        onClick={(e) => {
                            if (e.target === fileInputRef.current) return;
                            if (extractionState.isExtracting) return;
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
                                if (selectedFile) handleFile(selectedFile);
                            }}
                        />

                        {/* Background Effect */}
                        <div className="absolute inset-0 bg-gradient-to-b from-transparent to-cyan-900/5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"></div>

                        {extractionState.isExtracting ? (
                            <div className="text-center w-full z-10">
                                <div className="w-24 h-24 bg-gradient-to-br from-cyan-500/20 to-violet-500/20 rounded-full flex items-center justify-center mx-auto mb-6 relative">
                                    <div className="absolute inset-0 border-4 border-cyan-500/30 rounded-full animate-spin-slow"></div>
                                    <Music className="w-10 h-10 text-cyan-400 animate-pulse" />
                                </div>
                                <h3 className="text-xl font-bold text-white mb-2">오디오 추출 중...</h3>
                                <p className="text-slate-400 mb-6">{extractionState.status}</p>

                                <div className="w-64 mx-auto bg-slate-700/50 rounded-full h-2 mb-2">
                                    <div
                                        className="bg-gradient-to-r from-cyan-500 to-violet-500 h-2 rounded-full transition-all duration-300 shadow-[0_0_10px_rgba(6,182,212,0.5)]"
                                        style={{ width: `${extractionState.progress}%` }}
                                    />
                                </div>
                                <p className="text-sm text-cyan-400 font-mono">
                                    {extractionState.progress > 0 ? `${Math.round(extractionState.progress)}%` : '준비 중...'}
                                </p>
                            </div>
                        ) : file ? (
                            <div className="text-center w-full flex flex-col items-center z-10 animate-fade-in">
                                {previewUrl ? (
                                    <div className="relative w-full rounded-xl overflow-hidden bg-black/50 mb-6 shadow-2xl border border-slate-700/50 group-hover:border-cyan-500/30 transition-colors">
                                        <video
                                            src={previewUrl}
                                            controls
                                            className="w-full max-h-[280px] object-contain"
                                        />
                                    </div>
                                ) : (
                                    <div className="mb-6">
                                        <VideoFileIcon />
                                    </div>
                                )}

                                <h3 className="text-xl font-bold text-white mb-1 px-4 truncate max-w-md">{file.name}</h3>
                                <p className="text-sm text-slate-400 mb-4 font-mono">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>

                                {isExtractionComplete ? (
                                    <div className="flex items-center gap-2 px-4 py-2 bg-green-500/10 text-green-400 rounded-full border border-green-500/20 animate-bounce-subtle">
                                        <CheckCircle2 className="w-5 h-5" />
                                        <span className="font-medium">음성 추출 완료</span>
                                    </div>
                                ) : (
                                    <p className="text-xs text-cyan-400 opacity-80 mt-2">클릭하여 다른 파일 선택</p>
                                )}
                            </div>
                        ) : (
                            <div className="text-center z-10">
                                <div className="w-24 h-24 bg-slate-800/50 rounded-full flex items-center justify-center mx-auto mb-6 group-hover:scale-110 transition-transform duration-300 border border-slate-700 group-hover:border-cyan-500/50">
                                    <Upload className="w-10 h-10 text-slate-400 group-hover:text-cyan-400 transition-colors" />
                                </div>
                                <h3 className="text-xl font-bold text-white mb-2 group-hover:text-cyan-300 transition-colors">비디오 파일 업로드</h3>
                                <p className="text-slate-400 text-sm mb-6">여기로 파일을 드래그하거나 클릭하세요</p>
                                <div className="flex flex-wrap justify-center gap-2 text-xs text-slate-500">
                                    {ALLOWED_EXTENSIONS.map(ext => (
                                        <span key={ext} className="px-2 py-1 bg-slate-800 rounded border border-slate-700 uppercase">{ext.slice(1)}</span>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Action Buttons */}
                    <div className="flex justify-end gap-4">
                        {file && isVideoFile(file) && !isExtractionComplete && (
                            <button
                                onClick={handleExtractAudio}
                                disabled={!canExtract}
                                className={`
                                    flex items-center gap-2 px-6 py-3 rounded-lg font-bold transition-all text-white
                                    ${canExtract
                                        ? 'bg-gradient-to-r from-slate-700 to-slate-600 hover:from-slate-600 hover:to-slate-500 shadow-lg hover:shadow-cyan-500/20'
                                        : 'bg-slate-800 text-slate-500 cursor-not-allowed'}
                                `}
                            >
                                <Music className="w-5 h-5" />
                                1. 음성 추출하기
                            </button>
                        )}

                        <button
                            onClick={handleStartDubbing}
                            disabled={!canStartDubbing}
                            className={`
                                flex items-center gap-2 px-8 py-3 rounded-lg font-bold text-lg transition-all text-white min-w-[200px] justify-center
                                ${canStartDubbing
                                    ? 'bg-gradient-to-r from-cyan-500 to-violet-500 hover:from-cyan-400 hover:to-violet-400 shadow-lg hover:shadow-cyan-500/40 transform hover:-translate-y-0.5'
                                    : 'bg-slate-800 text-slate-500 cursor-not-allowed'}
                            `}
                        >
                            {isSubmitting ? <Loader2 className="w-5 h-5 animate-spin" /> : <ArrowRight className="w-5 h-5" />}
                            {isExtractionComplete ? '2. 더빙 시작하기' : '더빙 시작하기'}
                        </button>
                    </div>
                </div>

                {/* Settings Panel (Right side, takes 2 columns) */}
                <div className="lg:col-span-2 space-y-4">
                    <div className="glass-panel p-6 h-full flex flex-col">
                        <div className="flex items-center justify-between mb-6">
                            <h3 className="text-lg font-bold flex items-center gap-2 text-white">
                                <Settings className="w-5 h-5 text-cyan-400" />
                                더빙 설정
                            </h3>
                            <button
                                onClick={() => setShowAdvanced(!showAdvanced)}
                                className="text-xs text-slate-400 hover:text-white flex items-center gap-1"
                            >
                                {showAdvanced ? '간편 설정' : '고급 설정'}
                                {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                            </button>
                        </div>

                        <div className="space-y-6 flex-1">
                            {/* Languages */}
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-xs font-bold text-cyan-400 uppercase mb-2 ml-1 tracking-wider">원본 언어</label>
                                    <div className="relative group">
                                        <select
                                            value={settings.sourceLang}
                                            onChange={(e) => setSettings({ ...settings, sourceLang: e.target.value })}
                                            className="w-full bg-slate-800 border-2 border-slate-700 text-white font-medium rounded-xl p-3.5 appearance-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500 outline-none transition-all cursor-pointer hover:border-slate-600"
                                            disabled={isSubmitting}
                                        >
                                            {LANGUAGES.source.map(lang => (
                                                <option key={lang.value} value={lang.value}>{lang.label}</option>
                                            ))}
                                        </select>
                                        <ChevronDown className="absolute right-3 top-4 w-4 h-4 text-slate-400 group-hover:text-white transition-colors pointer-events-none" />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs font-bold text-violet-400 uppercase mb-2 ml-1 tracking-wider">목표 언어</label>
                                    <div className="relative group">
                                        <select
                                            value={settings.targetLang}
                                            onChange={(e) => setSettings({ ...settings, targetLang: e.target.value })}
                                            className="w-full bg-slate-800 border-2 border-slate-700 text-white font-medium rounded-xl p-3.5 appearance-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500 outline-none transition-all cursor-pointer hover:border-slate-600"
                                            disabled={isSubmitting}
                                        >
                                            {LANGUAGES.target.map(lang => (
                                                <option key={lang.value} value={lang.value}>{lang.label}</option>
                                            ))}
                                        </select>
                                        <ChevronDown className="absolute right-3 top-4 w-4 h-4 text-slate-400 group-hover:text-white transition-colors pointer-events-none" />
                                    </div>
                                    {/* Recommended Settings Summary */}
                                    <div className="mt-2 text-xs bg-emerald-500/10 px-3 py-2 rounded-lg border border-emerald-500/20">
                                        <div className="flex items-center gap-1.5 mb-2 text-emerald-400 font-bold">
                                            <span>💡</span> 추천 설정 자동 적용됨
                                        </div>
                                        <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-emerald-400/70">
                                            <div className="text-right font-semibold text-emerald-300">TTS:</div>
                                            <div><strong className="text-emerald-300">{recommendation.ttsEngine.toUpperCase()}</strong> — {recommendation.ttsReason}</div>

                                            <div className="text-right font-semibold text-emerald-300">STT:</div>
                                            <div><strong className="text-emerald-300">{recommendation.sttEngine.toUpperCase()}</strong> — {recommendation.sttReason}</div>

                                            <div className="text-right font-semibold text-emerald-300">싱크:</div>
                                            <div><strong className="text-emerald-300">{recommendation.syncName}</strong> — {recommendation.syncReason}</div>
                                        </div>
                                    </div>
                                </div>
                            </div>


                            {/* Options */}
                            <div className="space-y-4 pt-2">
                                <label className={`flex items-center gap-4 p-4 rounded-xl border-2 transition-all cursor-pointer relative overflow-hidden group ${settings.cloneVoice ? 'bg-cyan-500/10 border-cyan-500 shadow-[0_0_20px_rgba(6,182,212,0.2)]' : 'bg-slate-800/40 border-slate-700 hover:border-slate-500 hover:bg-slate-800'}`}>
                                    <div className={`w-6 h-6 rounded-md border-2 flex items-center justify-center transition-all duration-300 ${settings.cloneVoice ? 'bg-cyan-500 border-cyan-500 scale-110 shadow-lg shadow-cyan-500/50' : 'border-slate-500 group-hover:border-cyan-400'}`}>
                                        <CheckCircle2 className={`w-4 h-4 text-white transition-transform ${settings.cloneVoice ? 'scale-100' : 'scale-0'}`} />
                                    </div>
                                    <input
                                        type="checkbox"
                                        className="hidden"
                                        checked={settings.cloneVoice}
                                        onChange={(e) => setSettings({ ...settings, cloneVoice: e.target.checked })}
                                        disabled={isSubmitting}
                                    />
                                    <div className="flex-1 relative z-10">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`text-base font-bold transition-colors ${settings.cloneVoice ? 'text-yellow-400' : 'text-slate-200'}`}>음성 복제 사용</span>
                                            <Mic2 className={`w-4 h-4 ${settings.cloneVoice ? 'text-yellow-400' : 'text-slate-500'}`} />
                                        </div>
                                        <p className={`text-xs transition-colors leading-relaxed ${settings.cloneVoice ? 'text-yellow-100/70' : 'text-slate-500'}`}>
                                            원본 화자의 목소리 톤과 특징을 AI가 분석하여 그대로 재현합니다.
                                        </p>
                                    </div>
                                </label>

                                <label className={`flex items-center gap-4 p-4 rounded-xl border-2 transition-all cursor-pointer relative overflow-hidden group ${settings.verifyTranslation ? 'bg-violet-500/10 border-violet-500 shadow-[0_0_20px_rgba(139,92,246,0.2)]' : 'bg-slate-800/40 border-slate-700 hover:border-slate-500 hover:bg-slate-800'}`}>
                                    <div className={`w-6 h-6 rounded-md border-2 flex items-center justify-center transition-all duration-300 ${settings.verifyTranslation ? 'bg-violet-500 border-violet-500 scale-110 shadow-lg shadow-violet-500/50' : 'border-slate-500 group-hover:border-violet-400'}`}>
                                        <CheckCircle2 className={`w-4 h-4 text-white transition-transform ${settings.verifyTranslation ? 'scale-100' : 'scale-0'}`} />
                                    </div>
                                    <input
                                        type="checkbox"
                                        className="hidden"
                                        checked={settings.verifyTranslation}
                                        onChange={(e) => setSettings({ ...settings, verifyTranslation: e.target.checked })}
                                        disabled={isSubmitting}
                                    />
                                    <div className="flex-1 relative z-10">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`text-base font-bold transition-colors ${settings.verifyTranslation ? 'text-yellow-400' : 'text-slate-200'}`}>AI 번역 검증</span>
                                            <ShieldCheck className={`w-4 h-4 ${settings.verifyTranslation ? 'text-yellow-400' : 'text-slate-500'}`} />
                                        </div>
                                        <p className={`text-xs transition-colors leading-relaxed ${settings.verifyTranslation ? 'text-yellow-100/70' : 'text-slate-500'}`}>
                                            Gemini Pro가 번역 품질을 실시간으로 감수하고 오역을 수정합니다.
                                        </p>
                                    </div>
                                </label>
                            </div>

                            {/* Advanced Settings */}
                            {showAdvanced && (
                                <div className="space-y-8 pt-6 border-t border-slate-700/50 animate-fade-in mt-4">
                                    {/* Sync Mode */}
                                    <div>
                                        <label className="block text-xs font-bold text-slate-400 uppercase mb-3 tracking-wider flex items-center gap-2">
                                            <div className="w-1 h-4 bg-gradient-to-b from-cyan-500 to-violet-500 rounded-full"></div>
                                            싱크 및 속도 조절
                                        </label>
                                        <div className="space-y-3">
                                            {[
                                                { id: 'optimize', label: '자연스러운 속도 (Natural)', desc: '원래 말하기 속도를 유지합니다 (오디오가 짧으면 뒷부분이 비거나 싱크가 안 맞을 수 있음)', icon: Film, color: 'text-cyan-400', glowColor: '0, 200, 220', borderClass: 'border-cyan-500', bgClass: 'bg-cyan-500/10' },
                                                { id: 'speed_audio', label: '영상 길이에 맞춤 (Speed Sync)', desc: '오디오 전체 길이를 영상에 강제로 맞춥니다 (대화가 끊이지 않는 영상에 추천)', icon: Gauge, color: 'text-emerald-400', glowColor: '16, 185, 129', borderClass: 'border-emerald-500', bgClass: 'bg-emerald-500/10' },
                                                { id: 'stretch', label: '영상 속도 조절', desc: '영상을 느리게 재생해 음성 길이에 맞춥니다', icon: Clock, color: 'text-violet-400', glowColor: '139, 92, 246', borderClass: 'border-violet-500', bgClass: 'bg-violet-500/10' }
                                            ].map(mode => {
                                                const isActive = settings.syncMode === mode.id;
                                                return (
                                                    <label
                                                        key={mode.id}
                                                        className={`flex items-center gap-4 p-4 rounded-xl border-2 cursor-pointer transition-all group relative ${isActive ? `${mode.bgClass} ${mode.borderClass}` : 'bg-slate-800/30 border-slate-700 hover:border-slate-600 hover:bg-slate-800'}`}
                                                        style={isActive ? { boxShadow: `0 0 25px rgba(${mode.glowColor}, 0.4), 0 0 50px rgba(${mode.glowColor}, 0.2)` } : {}}
                                                    >
                                                        <div className={`w-6 h-6 rounded-md border-2 flex items-center justify-center transition-all duration-300 flex-shrink-0 ${isActive ? `${mode.borderClass.replace('border-', 'bg-').replace('-500', '-500')} ${mode.borderClass} scale-110 shadow-lg` : 'border-slate-500 group-hover:border-slate-400'}`}
                                                            style={isActive ? { boxShadow: `0 0 10px rgba(${mode.glowColor}, 0.5)` } : {}}
                                                        >
                                                            <CheckCircle2 className={`w-4 h-4 text-white transition-transform ${isActive ? 'scale-100' : 'scale-0'}`} />
                                                        </div>
                                                        <input
                                                            type="radio"
                                                            name="syncMode"
                                                            value={mode.id}
                                                            checked={isActive}
                                                            onChange={(e) => setSettings({ ...settings, syncMode: e.target.value })}
                                                            className="hidden"
                                                        />
                                                        <div className="flex-1">
                                                            <div className="flex items-center gap-2 mb-1">
                                                                <mode.icon className={`w-5 h-5 ${isActive ? 'text-yellow-400' : mode.color}`} />
                                                                <span className={`text-base font-bold transition-colors ${isActive ? 'text-yellow-400' : 'text-slate-300'}`}>{mode.label}</span>
                                                            </div>
                                                            <p className={`text-xs transition-colors leading-relaxed ${isActive ? 'text-yellow-100/80' : 'text-slate-500'}`}>{mode.desc}</p>
                                                        </div>
                                                    </label>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* TTS Engine */}
                                    <div>
                                        <label className="block text-xs font-bold text-slate-400 uppercase mb-3 tracking-wider flex items-center gap-2">
                                            <div className="w-1 h-4 bg-violet-500 rounded-full"></div>
                                            음성 합성 (TTS) 엔진
                                        </label>
                                        <div className="space-y-4">
                                            {[
                                                { id: 'auto', label: '자동 (Auto)', desc: '스마트 선택' },
                                                { id: 'xtts', label: 'XTTS v2', desc: '고품질 복제' },
                                                { id: 'edge', label: 'Edge TTS', desc: '빠른 낭독' },
                                                { id: 'silero', label: 'Silero', desc: '초고속' },
                                                { id: 'elevenlabs', label: 'ElevenLabs', desc: '최상급 품격' },
                                                { id: 'openai', label: 'OpenAI', desc: '자연스러움' }
                                            ].map((engine, index) => {
                                                const isActive = settings.ttsEngine === engine.id;
                                                return (
                                                    <div key={engine.id}>
                                                        <label className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all group ${isActive ? 'bg-violet-500/15 border-violet-500 shadow-[0_0_25px_rgba(139,92,246,0.4)]' : 'bg-slate-800/50 border-slate-600 hover:border-slate-500 hover:bg-slate-800/70'}`}>
                                                            <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all duration-300 flex-shrink-0 ${isActive ? 'bg-violet-500 border-violet-500 scale-110 shadow-lg shadow-violet-500/50' : 'border-slate-500 group-hover:border-violet-400'}`}>
                                                                <Check className={`w-3.5 h-3.5 text-white stroke-[3] transition-transform ${isActive ? 'scale-100' : 'scale-0'}`} />
                                                            </div>
                                                            <input
                                                                type="radio"
                                                                name="ttsEngine"
                                                                value={engine.id}
                                                                checked={isActive}
                                                                onChange={(e) => setSettings({ ...settings, ttsEngine: e.target.value })}
                                                                className="hidden"
                                                            />
                                                            <div className="flex-1">
                                                                <span className={`text-sm font-bold transition-colors ${isActive ? 'text-yellow-400' : 'text-slate-300'}`}>{engine.label}</span>
                                                                <span className={`text-xs transition-colors ml-2 ${isActive ? 'text-yellow-200/80' : 'text-slate-500'}`}>— {engine.desc}</span>
                                                            </div>
                                                        </label>
                                                        {index < 5 && <div className="border-t-2 border-slate-600 my-4"></div>}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* Translation & STT Engine Group */}
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                        {/* Translation Engine */}
                                        <div>
                                            <label className="block text-xs font-bold text-slate-400 uppercase mb-3 tracking-wider flex items-center gap-2">
                                                <div className="w-1 h-4 bg-emerald-500 rounded-full"></div>
                                                번역 엔진
                                            </label>
                                            <div className="space-y-4">
                                                {[
                                                    { id: 'gemini', label: 'Gemini 2.5 Flash', desc: '최고 품질 / 다국어 특화' },
                                                    { id: 'groq', label: 'Groq API', desc: '초고속 / 온라인' },
                                                    { id: 'local', label: 'Local (Ollama)', desc: '무료 / 로컬' }
                                                ].map((engine, index) => (
                                                    <div key={engine.id}>
                                                        <label className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all group ${settings.translationEngine === engine.id ? 'bg-emerald-500/15 border-emerald-500 shadow-[0_0_25px_rgba(16,185,129,0.4)]' : 'bg-slate-800/50 border-slate-600 hover:border-slate-500 hover:bg-slate-800/70'}`}>
                                                            <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all duration-300 flex-shrink-0 ${settings.translationEngine === engine.id ? 'bg-emerald-500 border-emerald-500 scale-110 shadow-lg shadow-emerald-500/50' : 'border-slate-500 group-hover:border-emerald-400'}`}>
                                                                <Check className={`w-3.5 h-3.5 text-white stroke-[3] transition-transform ${settings.translationEngine === engine.id ? 'scale-100' : 'scale-0'}`} />
                                                            </div>
                                                            <input
                                                                type="radio"
                                                                name="translationEngine"
                                                                value={engine.id}
                                                                checked={settings.translationEngine === engine.id}
                                                                onChange={(e) => setSettings({ ...settings, translationEngine: e.target.value })}
                                                                className="hidden"
                                                            />
                                                            <div className="flex-1">
                                                                <span className={`text-sm font-bold transition-colors ${settings.translationEngine === engine.id ? 'text-yellow-400' : 'text-slate-300'}`}>{engine.label}</span>
                                                                <span className={`text-xs transition-colors ml-2 ${settings.translationEngine === engine.id ? 'text-yellow-200/80' : 'text-slate-500'}`}>— {engine.desc}</span>
                                                            </div>
                                                        </label>
                                                        {index === 0 && <div className="border-t-2 border-slate-600 my-4"></div>}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>

                                        {/* STT Engine */}
                                        <div>
                                            <label className="block text-xs font-bold text-slate-400 uppercase mb-3 tracking-wider flex items-center gap-2">
                                                <div className="w-1 h-4 bg-blue-500 rounded-full"></div>
                                                음성 인식 (STT)
                                            </label>
                                            <div className="space-y-4">
                                                {[
                                                    { id: 'groq', label: 'Groq API', desc: '초고속 / 온라인' },
                                                    { id: 'local', label: 'Local (Whisper)', desc: 'GPU 필요' },
                                                    { id: 'openai', label: 'OpenAI API', desc: '최고 정확도' }
                                                ].map((engine, index) => (
                                                    <div key={engine.id}>
                                                        <label className={`flex items-center gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all group ${settings.sttEngine === engine.id ? 'bg-blue-500/15 border-blue-500 shadow-[0_0_25px_rgba(59,130,246,0.4)]' : 'bg-slate-800/50 border-slate-600 hover:border-slate-500 hover:bg-slate-800/70'}`}>
                                                            <div className={`w-5 h-5 rounded border-2 flex items-center justify-center transition-all duration-300 flex-shrink-0 ${settings.sttEngine === engine.id ? 'bg-blue-500 border-blue-500 scale-110 shadow-lg shadow-blue-500/50' : 'border-slate-500 group-hover:border-blue-400'}`}>
                                                                <Check className={`w-3.5 h-3.5 text-white stroke-[3] transition-transform ${settings.sttEngine === engine.id ? 'scale-100' : 'scale-0'}`} />
                                                            </div>
                                                            <input
                                                                type="radio"
                                                                name="sttEngine"
                                                                value={engine.id}
                                                                checked={settings.sttEngine === engine.id}
                                                                onChange={(e) => setSettings({ ...settings, sttEngine: e.target.value })}
                                                                className="hidden"
                                                            />
                                                            <div className="flex-1">
                                                                <span className={`text-sm font-bold transition-colors ${settings.sttEngine === engine.id ? 'text-yellow-400' : 'text-slate-300'}`}>{engine.label}</span>
                                                                <span className={`text-xs transition-colors ml-2 ${settings.sttEngine === engine.id ? 'text-yellow-200/80' : 'text-slate-500'}`}>— {engine.desc}</span>
                                                            </div>
                                                        </label>
                                                        {index < 2 && <div className="border-t-2 border-slate-600 my-4"></div>}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Error Message */}
            {error && (
                <div className="mt-8 p-4 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center justify-between animate-shake">
                    <div className="flex items-center gap-3">
                        <AlertCircle className="w-5 h-5 text-red-500" />
                        <span className="text-red-400 font-medium">{error}</span>
                    </div>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-white">
                        <span className="sr-only">닫기</span>
                        ✕
                    </button>
                </div>
            )}
        </div>
    );
}

function VideoFileIcon() {
    return (
        <svg className="w-16 h-16 mx-auto text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
            <polyline points="14 2 14 8 20 8" />
            <path d="M10 13l2 2 4-4" />
        </svg>
    );
}
