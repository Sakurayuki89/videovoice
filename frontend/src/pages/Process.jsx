import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
    CheckCircle2, Loader2, AlertCircle, Terminal,
    FileAudio, FileText, Languages, Speech, Film, XCircle,
    ChevronDown, ChevronUp, Clock, Hourglass, ArrowRight, Zap, Cloud
} from 'lucide-react';
import { getJob, cancelJob } from '../services/api';
import { useSystemStatus } from '../hooks/useSystemStatus';
import {
    JOB_POLL_INTERVAL as POLL_INTERVAL,
    MAX_POLL_RETRIES as MAX_RETRIES,
} from '../config';

export default function Process() {
    const { jobId } = useParams();
    const navigate = useNavigate();
    const [job, setJob] = useState(null);
    const [error, setError] = useState(null);
    const [retryCount, setRetryCount] = useState(0);
    const [isCancelling, setIsCancelling] = useState(false);
    const [loadingTime, setLoadingTime] = useState(0);
    const [elapsedTime, setElapsedTime] = useState(0);
    const [showLogs, setShowLogs] = useState(false);
    const logsEndRef = useRef(null);
    const startTimeRef = useRef(Date.now());

    // Fetch system status for API info
    const { status: systemStatus, isOnline } = useSystemStatus(true); // Always fetch on process page

    // Steps configuration
    const steps = [
        { key: 'extract', label: '오디오 추출', icon: FileAudio, desc: '영상에서 음성 분리' },
        { key: 'transcribe', label: '음성 인식', icon: FileText, desc: '음성을 텍스트로 변환' },
        { key: 'translate', label: 'AI 번역', icon: Languages, desc: '다국어 번역 수행' },
        { key: 'tts', label: '음성 합성', icon: Speech, desc: '새로운 목소리 생성' },
        { key: 'merge', label: '영상 병합', icon: Film, desc: '최종 비디오 완성' },
    ];

    const handleCancel = useCallback(async () => {
        if (isCancelling) return;
        setIsCancelling(true);
        try {
            await cancelJob(jobId);
            setJob(prev => prev ? { ...prev, status: 'cancelled' } : null);
        } catch (err) {
            console.error('Failed to cancel:', err);
            setError(err.message || 'Failed to cancel job');
        } finally {
            setIsCancelling(false);
        }
    }, [jobId, isCancelling]);

    // Initial loading timer
    useEffect(() => {
        let timer;
        if (!job && !error) {
            timer = setInterval(() => setLoadingTime(p => p + 1), 1000);
        }
        return () => clearInterval(timer);
    }, [job, error]);

    // Elapsed time timer
    useEffect(() => {
        let timer;
        if (job && (job.status === 'processing' || job.status === 'queued')) {
            timer = setInterval(() => {
                setElapsedTime(Math.floor((Date.now() - startTimeRef.current) / 1000));
            }, 1000);
        }
        return () => clearInterval(timer);
    }, [job]);

    // Status polling
    useEffect(() => {
        let intervalId;
        let isMounted = true;

        const fetchStatus = async () => {
            if (!isMounted) return;
            try {
                const data = await getJob(jobId);
                if (!isMounted) return;

                setJob(data);
                setRetryCount(0);
                setError(null);

                if (data.status === 'completed') {
                    clearInterval(intervalId);
                    setTimeout(() => {
                        if (isMounted) navigate(`/result/${jobId}`);
                    }, 1500); // Give user a moment to see 100%
                } else if (data.status === 'failed' || data.status === 'cancelled') {
                    clearInterval(intervalId);
                }
            } catch (err) {
                console.error(err);
                if (!isMounted) return;

                if (err.message && (err.message.includes('not found') || err.message.includes('404'))) {
                    setError('작업을 찾을 수 없습니다. (서버가 재시작되었을 수 있습니다)');
                    clearInterval(intervalId);
                } else if (retryCount < MAX_RETRIES) {
                    setRetryCount(prev => prev + 1);
                } else {
                    setError(err.message || "Failed to fetch job status");
                    clearInterval(intervalId);
                }
            }
        };

        fetchStatus();
        intervalId = setInterval(fetchStatus, POLL_INTERVAL);
        return () => {
            isMounted = false;
            clearInterval(intervalId);
        };
    }, [jobId, navigate, retryCount]);

    // Auto-scroll logs
    useEffect(() => {
        if (showLogs) {
            logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
    }, [job?.logs, showLogs]);

    const formatTime = (seconds) => {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}분 ${secs}초`;
    };

    const calculateETA = () => {
        if (!job || job.status !== 'processing') return null;
        const progress = job.progress || 1;
        if (progress >= 100) return '완료됨';

        // Simple linear extrapolation
        const estimatedTotal = (elapsedTime / progress) * 100;
        const remaining = Math.max(0, estimatedTotal - elapsedTime);

        if (remaining < 60) return '곧 완료';
        return `약 ${Math.ceil(remaining / 60)}분 남음`;
    };

    const currentStepIndex = job ? steps.findIndex(s => s.key === job.current_step) : -1;
    const latestLog = job?.logs && job.logs.length > 0 ? job.logs[job.logs.length - 1].message : '대기 중...';

    // Check used APIs based on job settings
    const usesElevenLabs = job?.settings?.tts_engine === 'elevenlabs';
    const usesGroq = job?.settings?.translation_engine === 'groq' || job?.settings?.stt_engine === 'groq';
    const usesOpenAI = job?.settings?.tts_engine === 'openai' || job?.settings?.stt_engine === 'openai';

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-center">
                <div className="w-20 h-20 bg-red-500/10 rounded-full flex items-center justify-center mb-6 border border-red-500/20">
                    <AlertCircle className="w-10 h-10 text-red-500" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">오류가 발생했습니다</h2>
                <p className="text-slate-400 mb-8 max-w-md bg-slate-800/50 p-4 rounded-lg border border-slate-700">
                    {error}
                </p>
                <div className="flex gap-4">
                    <button
                        onClick={() => { setError(null); setRetryCount(0); }}
                        className="btn-secondary"
                    >
                        다시 시도
                    </button>
                    <button onClick={() => navigate('/')} className="btn-primary">
                        홈으로 이동
                    </button>
                </div>
            </div>
        );
    }

    if (!job) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[60vh]">
                <div className="relative mb-8">
                    <div className="absolute inset-0 bg-cyan-500/20 blur-xl rounded-full animate-pulse"></div>
                    <Loader2 className="w-16 h-16 animate-spin text-cyan-400 relative z-10" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">작업 로딩 중...</h2>
                <p className="text-slate-400">서버 상태를 확인하고 있습니다 ({loadingTime}초)</p>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto py-12 px-4">
            {/* Header Section */}
            <div className="text-center mb-12">
                <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-slate-300 text-sm mb-6">
                    <span className={`w-2 h-2 rounded-full ${job.status === 'processing' ? 'bg-cyan-500 animate-pulse' :
                        job.status === 'completed' ? 'bg-green-500' : 'bg-slate-500'}`} />
                    Job ID: <span className="font-mono text-slate-400">{jobId.split('-')[0]}...</span>
                </div>

                <h1 className="text-4xl md:text-5xl font-extrabold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 via-blue-500 to-violet-500">
                    {job.status === 'processing' ? 'AI 더빙 작업 중' :
                        job.status === 'completed' ? '작업 완료!' :
                            job.status === 'failed' ? '작업 실패' : '대기 중'}
                </h1>

                {/* Real-time Log Ticker */}
                <div className="h-8 mt-4 overflow-hidden relative max-w-2xl mx-auto">
                    <div className="absolute inset-0 flex items-center justify-center transition-all duration-300 transform">
                        <p className="text-cyan-300/80 font-mono text-sm flex items-center gap-2 animate-fade-in">
                            <Terminal className="w-4 h-4" />
                            {latestLog}
                            <span className="w-1.5 h-4 bg-cyan-500/50 animate-pulse ml-1" />
                        </p>
                    </div>
                </div>
            </div>

            {/* Main Dashboard Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">

                {/* 1. Progress Card (Span 2) */}
                <div className="lg:col-span-2 glass-panel p-8 relative overflow-hidden group min-h-[300px] flex flex-col justify-center">

                    <div className="relative z-10">
                        <div className="flex justify-between items-end mb-6">
                            <div>
                                <h3 className="text-lg font-bold text-white mb-1">전체 진행률</h3>
                                <p className="text-slate-400 text-sm">{steps[currentStepIndex]?.label || '준비 중'} 단계 진행 중</p>
                            </div>
                            <span className="text-4xl font-extrabold text-white tracking-tight">{job.progress}%</span>
                        </div>

                        {/* Progress Bar */}
                        <div className="h-4 bg-slate-700/50 rounded-full overflow-hidden mb-2">
                            <div
                                className="h-full bg-gradient-to-r from-cyan-500 via-blue-500 to-violet-500 transition-all duration-700 ease-out relative"
                                style={{ width: `${job.progress}%` }}
                            >
                                <div className="absolute inset-0 bg-white/30 animate-[shimmer_2s_infinite]"></div>
                            </div>
                        </div>
                        <div className="flex justify-end">
                            <span className="text-xs text-slate-500 font-mono">STEP {currentStepIndex + 1} / {steps.length}</span>
                        </div>
                    </div>
                </div>

                {/* 2. Side Panel (Time + API Info) */}
                <div className="glass-panel p-6 flex flex-col gap-6">
                    {/* Time Info */}
                    <div className="space-y-4">
                        <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center border border-blue-500/20">
                                <Clock className="w-4 h-4 text-blue-400" />
                            </div>
                            <div>
                                <p className="text-[10px] text-slate-500 uppercase tracking-wide">진행 시간</p>
                                <p className="text-lg font-bold text-white font-mono">{formatTime(elapsedTime)}</p>
                            </div>
                        </div>
                        <div className="w-full h-px bg-slate-700/50" />
                        <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg bg-violet-500/10 flex items-center justify-center border border-violet-500/20">
                                <Hourglass className="w-4 h-4 text-violet-400" />
                            </div>
                            <div>
                                <p className="text-[10px] text-slate-500 uppercase tracking-wide">예상 남은 시간</p>
                                <p className="text-lg font-bold text-white font-mono">{calculateETA() || '--'}</p>
                            </div>
                        </div>
                    </div>

                    {/* API Status Info (Only show if relevant APIs are used) */}
                    {(usesElevenLabs || usesGroq || usesOpenAI) && systemStatus?.api_status && (
                        <>
                            <div className="w-full h-px bg-slate-700/50" />
                            <div className="space-y-3">
                                <h4 className="text-xs font-bold text-slate-400 uppercase flex items-center gap-2">
                                    <Cloud className="w-3 h-3" />
                                    API 사용 현황
                                </h4>

                                {usesElevenLabs && systemStatus.api_status.elevenlabs === 'configured' && (
                                    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
                                        <div className="flex justify-between items-center mb-1">
                                            <span className="text-xs text-white">ElevenLabs</span>
                                            <span className="text-[10px] text-emerald-400">연결됨</span>
                                        </div>
                                        {systemStatus.api_status.elevenlabs_usage && (
                                            <>
                                                <div className="w-full bg-slate-700 rounded-full h-1 my-1.5">
                                                    <div
                                                        className="h-1 rounded-full bg-emerald-500"
                                                        style={{ width: `${Math.min(100, (systemStatus.api_status.elevenlabs_usage.used / systemStatus.api_status.elevenlabs_usage.limit) * 100)}%` }}
                                                    />
                                                </div>
                                                <div className="flex justify-between text-[10px] text-slate-500">
                                                    <span>
                                                        {systemStatus.api_status.elevenlabs_usage.used.toLocaleString()} / {systemStatus.api_status.elevenlabs_usage.limit.toLocaleString()}
                                                        <span className="ml-1 text-slate-400">
                                                            ({Math.round((systemStatus.api_status.elevenlabs_usage.used / systemStatus.api_status.elevenlabs_usage.limit) * 100)}%)
                                                        </span>
                                                    </span>
                                                    <span>{Math.max(0, Math.floor((systemStatus.api_status.elevenlabs_usage.limit - systemStatus.api_status.elevenlabs_usage.used) / 1000))}분 남음</span>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                )}

                                {usesGroq && (
                                    <div className="flex items-center justify-between bg-slate-800/50 rounded-lg p-2.5 border border-slate-700/50">
                                        <span className="text-xs text-white">Groq API</span>
                                        {systemStatus.api_status.groq === 'configured' ? (
                                            <div className="flex items-center gap-1.5">
                                                <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
                                                <span className="text-[10px] text-emerald-400">정상</span>
                                            </div>
                                        ) : (
                                            <span className="text-[10px] text-red-400">연결 끊김</span>
                                        )}
                                    </div>
                                )}

                                {usesOpenAI && (
                                    <div className="flex items-center justify-between bg-slate-800/50 rounded-lg p-2.5 border border-slate-700/50">
                                        <span className="text-xs text-white">OpenAI API</span>
                                        {systemStatus.api_status.openai === 'configured' ? (
                                            <div className="flex items-center gap-1.5">
                                                <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
                                                <span className="text-[10px] text-emerald-400">정상</span>
                                            </div>
                                        ) : (
                                            <span className="text-[10px] text-red-400">연결 끊김</span>
                                        )}
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </div>
            </div>

            {/* Timeline Stepper */}
            <div className="glass-panel p-8 mb-8 overflow-hidden">
                <h3 className="text-lg font-bold text-white mb-8 flex items-center gap-2">
                    작업 상세 단계
                </h3>

                <div className="relative px-4">
                    {/* Connecting Line - Background */}
                    <div className="absolute top-5 left-0 w-full h-1 bg-slate-800 rounded-full -z-10 hidden md:block"></div>

                    {/* Connecting Line - Filled */}
                    <div
                        className="absolute top-5 left-0 h-1 bg-gradient-to-r from-cyan-500 to-violet-500 rounded-full -z-10 transition-all duration-1000 hidden md:block"
                        style={{ width: `${Math.min(100, Math.max(0, (currentStepIndex / (steps.length - 1)) * 100))}%` }}
                    ></div>

                    <div className="flex flex-col md:flex-row justify-between gap-6 md:gap-0">
                        {steps.map((step, idx) => {
                            const isCompleted = idx < currentStepIndex || (job.steps?.[step.key] === 'done');
                            const isActive = idx === currentStepIndex && job.status === 'processing';
                            const isPending = idx > currentStepIndex;
                            const Icon = step.icon;

                            return (
                                <div key={step.key} className={`flex md:flex-col items-center gap-4 md:gap-0 relative group ${isPending ? 'opacity-50' : 'opacity-100'}`}>
                                    {/* Icon Circle */}
                                    <div className={`
                                        w-12 h-12 rounded-xl md:rounded-full flex items-center justify-center border-2 transition-all duration-300 z-10
                                        ${isActive ? 'bg-cyan-500 border-cyan-400 text-white shadow-[0_0_20px_rgba(6,182,212,0.5)] scale-110' :
                                            isCompleted ? 'bg-slate-900 border-violet-500 text-violet-400' :
                                                'bg-slate-900 border-slate-700 text-slate-600'}
                                    `}>
                                        {isActive ? <Loader2 className="w-5 h-5 animate-spin" /> :
                                            isCompleted ? <CheckCircle2 className="w-5 h-5" /> :
                                                <Icon className="w-5 h-5" />}
                                    </div>

                                    {/* Text Info */}
                                    <div className="md:mt-4 md:text-center w-full md:w-32">
                                        <p className={`text-sm font-bold transition-colors ${isActive ? 'text-white' : isCompleted ? 'text-violet-200' : 'text-slate-500'}`}>
                                            {step.label}
                                        </p>
                                        <p className="text-xs text-slate-500 hidden md:block mt-1">{step.desc}</p>

                                        {/* Mobile Progress Line (Vertical) */}
                                        <div className="md:hidden mt-1 text-xs text-slate-600">
                                            {isActive ? '작업 중...' : isCompleted ? '완료' : '대기'}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>

            {/* Logs Section */}
            <div className="glass-panel p-0 overflow-hidden border border-slate-800">
                <button
                    onClick={() => setShowLogs(!showLogs)}
                    className="w-full p-4 bg-slate-900/50 hover:bg-slate-800 transition-colors flex items-center justify-between text-slate-400 hover:text-white"
                >
                    <div className="flex items-center gap-3">
                        <Terminal className="w-5 h-5 text-slate-500" />
                        <span className="font-medium text-sm">상세 로그 기록</span>
                    </div>
                    {showLogs ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
                </button>

                <div
                    className={`transition-all duration-300 ease-in-out ${showLogs ? 'max-h-96' : 'max-h-0'}`}
                >
                    <div className="p-4 bg-black/80 font-mono text-xs text-slate-300 overflow-y-auto h-64 border-t border-slate-800">
                        {job.logs?.map((log, i) => (
                            <div key={i} className="mb-1 pl-3 border-l-2 border-slate-800 hover:border-cyan-500/50 transition-colors break-words">
                                <span className="text-slate-600 mr-2 select-none">[{new Date(log.timestamp).toLocaleTimeString()}]</span>
                                {log.message}
                            </div>
                        )) || <p className="text-slate-600 italic">로그가 없습니다.</p>}
                        <div ref={logsEndRef} />
                    </div>
                </div>
            </div>

            {/* Actions */}
            <div className="mt-8 flex justify-center">
                {job.status === 'processing' && (
                    <button
                        onClick={handleCancel}
                        disabled={isCancelling}
                        className="btn-text text-red-400 hover:text-red-300 hover:bg-red-500/10 px-6 py-2 rounded-lg transition-colors flex items-center gap-2"
                    >
                        {isCancelling ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />}
                        작업 취소하기
                    </button>
                )}

                {(job.status === 'failed' || job.status === 'cancelled') && (
                    <button onClick={() => navigate('/')} className="btn-primary px-8 py-3 flex items-center gap-2">
                        <ArrowRight className="w-5 h-5" />
                        새 작업 시작하기
                    </button>
                )}
            </div>
        </div>
    );
}

// Helper component
function ActivityIcon({ className }) {
    return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
        </svg>
    );
}
