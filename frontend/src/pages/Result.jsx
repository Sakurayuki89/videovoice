import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Download, ArrowLeft, FileText, CheckCircle2, AlertCircle, Loader2, RefreshCw, Film } from 'lucide-react';
import { getJob } from '../services/api';
import { API_BASE } from '../config';
import { useVideo } from '../contexts/VideoContext';
import { mergeVideoWithAudio, downloadBlob, downloadAudio } from '../utils/videoMerger';

/**
 * 서버 다운로드 엔드포인트를 통해 파일 다운로드 (Content-Disposition 지원)
 * 대용량 파일도 브라우저 메모리 문제 없이 다운로드 가능
 */
function serverDownload(jobId) {
    const url = `${API_BASE}/api/jobs/${jobId}/download`;
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

export default function Result() {
    const { jobId } = useParams();
    const navigate = useNavigate();
    const { originalVideo, clearVideo } = useVideo();

    const [job, setJob] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [videoError, setVideoError] = useState(false);

    // 클라이언트 측 비디오 병합 상태
    const [mergeState, setMergeState] = useState({
        isMerging: false,
        progress: 0,
        status: '',
        mergedVideoUrl: null,
        mergedBlob: null,
    });

    useEffect(() => {
        const fetchJob = async () => {
            setLoading(true);
            setError(null);
            try {
                console.log('[VideoVoice Result] Fetching job:', jobId);
                console.log('[VideoVoice Result] Original video in context:', originalVideo ? `${originalVideo.name} (${(originalVideo.size / 1024 / 1024).toFixed(1)}MB)` : 'NONE');

                const data = await getJob(jobId);
                console.log('[VideoVoice Result] Job data:', data.status, data.output_file);

                // Redirect if job is not completed
                if (data.status !== 'completed') {
                    if (data.status === 'processing' || data.status === 'queued') {
                        navigate(`/process/${jobId}`);
                    } else {
                        setError(`Job status: ${data.status}`);
                    }
                    return;
                }

                setJob(data);

                // 원본 비디오가 있고, 서버 결과가 오디오 파일(.wav, .mp3)인 경우에만 클라이언트 병합 수행
                // (.mp4인 경우 서버에서 이미 병합된 것이므로 다시 병합하지 않음 - 대용량 파일 FS Error 방지)
                const isAudioOutput = data.output_file && (data.output_file.endsWith('.wav') || data.output_file.endsWith('.mp3'));

                if (originalVideo && isAudioOutput) {
                    console.log('[VideoVoice Result] Server returned audio. Starting client-side merge...');
                    await performClientMerge(data.output_file);
                } else if (!data.output_file) {
                    console.warn('[VideoVoice Result] No output file from server');
                } else {
                    console.log('[VideoVoice Result] Server returned video or no original file. Skipping client merge.');
                }
            } catch (err) {
                console.error('[VideoVoice Result] Error:', err);
                setError(err.message || 'Failed to load job');
            } finally {
                setLoading(false);
            }
        };
        fetchJob();
    }, [jobId, navigate]);

    // 클라이언트 측 비디오 병합
    const performClientMerge = async (outputFile) => {
        try {
            setMergeState(prev => ({
                ...prev,
                isMerging: true,
                status: 'TTS 음성 다운로드 중...',
                progress: 0
            }));

            // 1. 서버에서 TTS 음성 다운로드
            const audioUrl = `${API_BASE}${outputFile}`;
            const audioBlob = await downloadAudio(audioUrl);

            setMergeState(prev => ({
                ...prev,
                status: '비디오 병합 준비 중...',
                progress: 20
            }));

            // 2. 브라우저에서 비디오 병합
            const mergedBlob = await mergeVideoWithAudio(
                originalVideo,
                audioBlob,
                (progress) => {
                    // FFmpeg 진행률을 20-90% 범위로 매핑
                    const mappedProgress = 20 + Math.round(progress * 0.7);
                    setMergeState(prev => ({ ...prev, progress: mappedProgress }));
                },
                (status) => {
                    setMergeState(prev => ({ ...prev, status }));
                }
            );

            // 3. Blob URL 생성
            const mergedUrl = URL.createObjectURL(mergedBlob);

            setMergeState({
                isMerging: false,
                progress: 100,
                status: '병합 완료!',
                mergedVideoUrl: mergedUrl,
                mergedBlob: mergedBlob
            });

        } catch (err) {
            console.error('Client merge failed:', err);
            setMergeState(prev => ({
                ...prev,
                isMerging: false,
                status: `병합 실패: ${err.message}`
            }));
            // 실패해도 서버 결과는 보여줌
        }
    };

    // 컴포넌트 언마운트 시 정리
    useEffect(() => {
        return () => {
            if (mergeState.mergedVideoUrl) {
                URL.revokeObjectURL(mergeState.mergedVideoUrl);
            }
        };
    }, [mergeState.mergedVideoUrl]);

    // 서버 비디오를 blob URL로 변환 (cross-origin 재생 지원)
    const [serverBlobUrl, setServerBlobUrl] = useState(null);
    useEffect(() => {
        if (job && job.output_file && !mergeState.mergedVideoUrl) {
            const url = `${API_BASE}${job.output_file}`;
            fetch(url)
                .then(res => {
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    return res.blob();
                })
                .then(blob => {
                    setServerBlobUrl(URL.createObjectURL(blob));
                })
                .catch(err => {
                    console.warn('[VideoVoice Result] Failed to fetch server video as blob:', err);
                });
        }
        return () => {
            if (serverBlobUrl) URL.revokeObjectURL(serverBlobUrl);
        };
    }, [job?.output_file]);

    // 병합된 비디오 다운로드
    const handleDownloadMerged = () => {
        if (mergeState.mergedBlob) {
            const filename = originalVideo?.name?.replace(/\.[^/.]+$/, '') || 'video';
            downloadBlob(mergeState.mergedBlob, `${filename}_dubbed.mp4`);
        }
    };

    // 새 비디오 처리 시 상태 초기화
    const handleNewVideo = () => {
        clearVideo();
        navigate('/');
    };

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[50vh]">
                <Loader2 className="w-8 h-8 animate-spin text-cyan-400 mb-4" />
                <p className="text-slate-400">결과 불러오는 중...</p>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[50vh] text-red-500">
                <AlertCircle className="w-12 h-12 mb-4" />
                <h2 className="text-xl font-bold">오류</h2>
                <p className="text-slate-400 mt-2">{error}</p>
                <button onClick={handleNewVideo} className="mt-4 btn-primary">
                    홈으로
                </button>
            </div>
        );
    }

    if (!job) return null;

    // 병합 중인 경우
    if (mergeState.isMerging) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[50vh]">
                <div className="glass-panel p-8 max-w-md w-full text-center">
                    <div className="w-20 h-20 bg-gradient-to-br from-cyan-500/20 to-violet-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                        <Film className="w-10 h-10 text-cyan-400 animate-pulse" />
                    </div>
                    <h2 className="text-xl font-bold text-white mb-2">비디오 병합 중</h2>
                    <p className="text-slate-400 mb-4">{mergeState.status}</p>
                    <div className="w-full bg-slate-700 rounded-full h-2 mb-2">
                        <div
                            className="bg-gradient-to-r from-cyan-500 to-violet-500 h-2 rounded-full transition-all duration-300"
                            style={{ width: `${mergeState.progress}%` }}
                        />
                    </div>
                    <p className="text-sm text-slate-500">{mergeState.progress}%</p>
                    <p className="text-xs text-slate-600 mt-4">
                        브라우저에서 처리 중이므로 서버 부하가 없습니다
                    </p>
                </div>
            </div>
        );
    }

    // 비디오 URL 결정 (병합 결과 또는 서버 blob 또는 서버 직접 URL)
    const hasClientMerge = mergeState.mergedVideoUrl && originalVideo;
    const videoUrl = hasClientMerge
        ? mergeState.mergedVideoUrl
        : serverBlobUrl || `${API_BASE}${job.output_file}`;

    const isAudioOnly = !hasClientMerge && job.output_file?.endsWith('.wav');

    // Calculate processing time if available
    const processingTime = job.completed_at && job.created_at
        ? Math.round((new Date(job.completed_at) - new Date(job.created_at)) / 1000)
        : null;

    const formatTime = (seconds) => {
        if (!seconds) return 'N/A';
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
    };

    return (
        <div className="max-w-6xl mx-auto py-8 px-4">
            <div className="mb-8">
                <button
                    onClick={handleNewVideo}
                    className="text-slate-400 hover:text-white flex items-center gap-2 mb-4 transition-colors"
                >
                    <ArrowLeft className="w-4 h-4" />
                    업로드로 돌아가기
                </button>
                <div className="flex items-center gap-4">
                    <div className="p-3 bg-green-500/10 rounded-full">
                        <CheckCircle2 className="w-8 h-8 text-green-400" />
                    </div>
                    <div>
                        <h1 className="text-3xl font-bold text-white">더빙 완료!</h1>
                        <p className="text-slate-400">
                            {hasClientMerge
                                ? `"${originalVideo.name}" 처리가 완료되었습니다.`
                                : job.input_filename
                                    ? `"${job.input_filename}" 처리가 완료되었습니다.`
                                    : '처리가 완료되었습니다.'}
                        </p>
                        {hasClientMerge && (
                            <p className="text-xs text-cyan-400 mt-1">
                                브라우저에서 병합 완료 - 서버 업로드 없이 처리됨
                            </p>
                        )}
                        {isAudioOnly && !originalVideo && (
                            <p className="text-xs text-orange-400 mt-1">
                                원본 비디오 없음 - 오디오만 출력됩니다 (페이지 새로고침 시 비디오 정보가 사라집니다)
                            </p>
                        )}
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Main Player (Video or Audio) */}
                <div className="lg:col-span-2 space-y-4">
                    <div className="glass-panel overflow-hidden p-1">
                        {videoError ? (
                            <div className="w-full aspect-video bg-slate-900 rounded-lg flex flex-col items-center justify-center">
                                <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
                                <p className="text-slate-400 mb-4">미디어를 불러올 수 없습니다</p>
                                <button
                                    onClick={() => setVideoError(false)}
                                    className="btn-secondary flex items-center gap-2"
                                >
                                    <RefreshCw className="w-4 h-4" />
                                    재시도
                                </button>
                            </div>
                        ) : isAudioOnly ? (
                            <div className="w-full bg-slate-900 rounded-lg p-8 flex flex-col items-center justify-center">
                                <div className="w-24 h-24 bg-gradient-to-br from-cyan-400 to-violet-500 rounded-full flex items-center justify-center mb-6">
                                    <svg className="w-12 h-12 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                                    </svg>
                                </div>
                                <p className="text-slate-400 mb-4">더빙된 오디오</p>
                                <audio
                                    controls
                                    className="w-full max-w-md"
                                    src={videoUrl}
                                    onError={() => setVideoError(true)}
                                >
                                    Your browser does not support the audio element.
                                </audio>
                            </div>
                        ) : (
                            <video
                                controls
                                className="w-full rounded-lg bg-black aspect-video"
                                src={videoUrl}
                                onError={() => setVideoError(true)}
                            >
                                Your browser does not support the video tag.
                            </video>
                        )}
                    </div>
                    <div className="flex justify-between items-center px-2">
                        <div>
                            <h3 className="text-lg font-medium text-white">
                                {isAudioOnly ? '결과 오디오' : '결과 비디오'}
                            </h3>
                            <p className="text-sm text-slate-500">
                                {job.settings?.source_lang?.toUpperCase() || 'AUTO'} →{' '}
                                {job.settings?.target_lang?.toUpperCase() || 'KO'}
                            </p>
                        </div>
                        {hasClientMerge ? (
                            <button
                                onClick={handleDownloadMerged}
                                className="btn-primary flex items-center gap-2 text-sm"
                            >
                                <Download className="w-4 h-4" />
                                MP4 다운로드
                            </button>
                        ) : (
                            <button
                                onClick={() => serverDownload(jobId)}
                                className="btn-primary flex items-center gap-2 text-sm"
                            >
                                <Download className="w-4 h-4" />
                                {isAudioOnly ? 'WAV 다운로드' : 'MP4 다운로드'}
                            </button>
                        )}
                    </div>
                </div>

                {/* Sidebar / Stats */}
                <div className="space-y-6">
                    {/* Quality Score Panel */}
                    {job.quality_result && (
                        <div className="glass-panel p-6">
                            <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                                <CheckCircle2 className="w-5 h-5 text-violet-400" />
                                번역 품질
                            </h3>

                            {/* Overall Score */}
                            <div className="text-center mb-4">
                                <div className={`text-4xl font-bold ${job.quality_result.overall_score >= 85 ? 'text-green-400' :
                                    job.quality_result.overall_score >= 60 ? 'text-yellow-400' :
                                        'text-red-400'
                                    }`}>
                                    {job.quality_result.overall_score}%
                                </div>
                                <div className={`text-xs font-medium mt-1 px-2 py-1 rounded inline-block ${job.quality_result.recommendation === 'APPROVED'
                                    ? 'bg-green-500/20 text-green-400' :
                                    job.quality_result.recommendation === 'REVIEW_NEEDED'
                                        ? 'bg-yellow-500/20 text-yellow-400' :
                                        'bg-red-500/20 text-red-400'
                                    }`}>
                                    {job.quality_result.recommendation === 'APPROVED' ? '✓ 승인됨' :
                                        job.quality_result.recommendation === 'REVIEW_NEEDED' ? '⚠ 검토 필요' :
                                            '✗ 수정 필요'}
                                </div>
                            </div>

                            {/* Breakdown */}
                            {job.quality_result.breakdown && (
                                <div className="space-y-2 text-sm">
                                    {[
                                        { key: 'accuracy', label: '정확도', weight: '40%' },
                                        { key: 'naturalness', label: '자연스러움', weight: '30%' },
                                        { key: 'dubbing_fit', label: '더빙 적합성', weight: '20%' },
                                        { key: 'consistency', label: '일관성', weight: '10%' }
                                    ].map(({ key, label, weight }) => (
                                        <div key={key}>
                                            <div className="flex justify-between text-slate-400 mb-1">
                                                <span>{label}</span>
                                                <span>{job.quality_result.breakdown[key]}%</span>
                                            </div>
                                            <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                                                <div
                                                    className={`h-full transition-all ${job.quality_result.breakdown[key] >= 85 ? 'bg-green-400' :
                                                        job.quality_result.breakdown[key] >= 60 ? 'bg-yellow-400' :
                                                            'bg-red-400'
                                                        }`}
                                                    style={{ width: `${job.quality_result.breakdown[key]}%` }}
                                                />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {/* Issues */}
                            {job.quality_result.issues && job.quality_result.issues.length > 0 && (
                                <div className="mt-4 pt-4 border-t border-slate-700">
                                    <p className="text-xs text-slate-500 mb-2">발견된 문제:</p>
                                    <ul className="text-xs text-slate-400 space-y-1">
                                        {job.quality_result.issues.slice(0, 3).map((issue, i) => (
                                            <li key={i} className="flex items-start gap-1">
                                                <span className="text-orange-400">•</span>
                                                {issue}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="glass-panel p-6">
                        <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                            <FileText className="w-5 h-5 text-cyan-400" />
                            다운로드
                        </h3>
                        <div className="space-y-3">
                            {hasClientMerge ? (
                                <button
                                    onClick={handleDownloadMerged}
                                    className="w-full flex items-center justify-between p-3 bg-slate-800/50 rounded-lg hover:bg-slate-700/50 transition-colors"
                                >
                                    <span className="text-sm text-slate-300">더빙된 비디오 (MP4)</span>
                                    <Download className="w-4 h-4 text-cyan-400" />
                                </button>
                            ) : (
                                <button
                                    onClick={() => serverDownload(jobId)}
                                    className="w-full flex items-center justify-between p-3 bg-slate-800/50 rounded-lg hover:bg-slate-700/50 transition-colors"
                                >
                                    <span className="text-sm text-slate-300">
                                        {isAudioOnly ? '더빙된 오디오 (WAV)' : '더빙된 비디오 (MP4)'}
                                    </span>
                                    <Download className="w-4 h-4 text-cyan-400" />
                                </button>
                            )}

                            {/* TTS 음성만 별도 다운로드 (원본 비디오가 있는 경우) */}
                            {hasClientMerge && (
                                <button
                                    onClick={() => serverDownload(jobId)}
                                    className="w-full flex items-center justify-between p-3 bg-slate-800/50 rounded-lg hover:bg-slate-700/50 transition-colors"
                                >
                                    <span className="text-sm text-slate-300">TTS 음성만 (WAV)</span>
                                    <Download className="w-4 h-4 text-slate-400" />
                                </button>
                            )}
                        </div>
                    </div>

                    <div className="glass-panel p-6">
                        <h3 className="font-bold text-white mb-4">작업 상세</h3>
                        <div className="space-y-4 text-sm">
                            <div className="flex justify-between">
                                <span className="text-slate-500">작업 ID</span>
                                <span className="text-slate-300 font-mono text-xs">{jobId.slice(0, 8)}...</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">원본 언어</span>
                                <span className="text-slate-300 uppercase">{job.settings?.source_lang || 'AUTO'}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">목표 언어</span>
                                <span className="text-slate-300 uppercase">{job.settings?.target_lang || 'KO'}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">음성 복제</span>
                                <span className="text-slate-300">{job.settings?.clone_voice ? '예' : '아니오'}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">품질 검증</span>
                                <span className="text-slate-300">{job.settings?.verify_translation ? '예' : '아니오'}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-500">처리 시간</span>
                                <span className="text-slate-300">{formatTime(processingTime)}</span>
                            </div>
                            {hasClientMerge && (
                                <div className="flex justify-between">
                                    <span className="text-slate-500">병합 방식</span>
                                    <span className="text-cyan-400">클라이언트</span>
                                </div>
                            )}
                            <div className="flex justify-between">
                                <span className="text-slate-500">완료 시각</span>
                                <span className="text-slate-300">
                                    {job.completed_at
                                        ? new Date(job.completed_at).toLocaleString('ko-KR')
                                        : 'N/A'}
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Process Another */}
                    <button
                        onClick={handleNewVideo}
                        className="block w-full text-center btn-secondary py-3"
                    >
                        다른 비디오 처리하기
                    </button>
                </div>
            </div>
        </div>
    );
}
