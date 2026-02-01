import { useState, useRef, useEffect } from 'react';
import { Video, Activity, Github, Cpu, HardDrive, RefreshCw, X, Check, AlertTriangle, Zap } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { useSystemStatus } from '../hooks/useSystemStatus';

function SystemStatusPopup({ isOpen, onClose, anchorRef }) {
    const { status, loading, error, refresh, isOnline } = useSystemStatus(isOpen);
    const popupRef = useRef(null);

    // Close on click outside
    useEffect(() => {
        const handleClickOutside = (e) => {
            if (popupRef.current && !popupRef.current.contains(e.target) &&
                anchorRef.current && !anchorRef.current.contains(e.target)) {
                onClose();
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
            return () => document.removeEventListener('mousedown', handleClickOutside);
        }
    }, [isOpen, onClose, anchorRef]);

    if (!isOpen) return null;

    // Helper to render compact API status
    const ApiItem = ({ name, status, usage = null }) => (
        <div className="flex flex-col p-2 bg-slate-800/50 rounded-lg border border-slate-700/50">
            <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-slate-300">{name}</span>
                {status === 'configured' ? (
                    <Check className="w-3 h-3 text-emerald-400" />
                ) : (
                    <AlertTriangle className="w-3 h-3 text-slate-600" />
                )}
            </div>

            {/* Show Quota for ElevenLabs if available */}
            {name === 'ElevenLabs' && usage && (
                <div className="mt-1">
                    <div className="flex items-center justify-between text-[10px] text-slate-400 mb-0.5">
                        <span>{Math.round((usage.used / usage.limit) * 100)}% 사용</span>
                        <span className="text-emerald-400">{Math.max(0, Math.floor((usage.limit - usage.used) / 1000))}분 남음</span>
                    </div>
                    <div className="w-full bg-slate-700 rounded-full h-1">
                        <div
                            className={`h-1 rounded-full transition-all ${usage.used / usage.limit > 0.9 ? 'bg-red-500' : 'bg-emerald-500'}`}
                            style={{ width: `${Math.min(100, (usage.used / usage.limit) * 100)}%` }}
                        />
                    </div>
                    <div className="text-[9px] text-slate-500 mt-0.5 text-right">
                        {usage.used.toLocaleString()} / {usage.limit.toLocaleString()} 자
                    </div>
                </div>
            )}
        </div>
    );

    return (
        <div
            ref={popupRef}
            className="absolute top-full right-0 mt-2 w-72 glass-panel p-3 shadow-2xl z-50 border border-slate-700/50 animate-fade-in origin-top-right"
        >
            <div className="flex items-center justify-between mb-3 px-1">
                <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-red-500'}`} />
                    <h3 className="font-bold text-white text-xs tracking-wide">SYSTEM STATUS</h3>
                </div>
                <div className="flex items-center gap-1">
                    <button onClick={refresh} disabled={loading} className="p-1 text-slate-400 hover:text-white transition-colors rounded hover:bg-slate-800">
                        <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                    </button>
                    <button onClick={onClose} className="p-1 text-slate-400 hover:text-white transition-colors rounded hover:bg-slate-800">
                        <X className="w-3.5 h-3.5" />
                    </button>
                </div>
            </div>

            {error ? (
                <div className="p-2 bg-red-500/10 border border-red-500/20 rounded text-center">
                    <p className="text-xs text-red-400">서버 연결 실패</p>
                </div>
            ) : loading ? (
                <div className="py-4 text-center text-xs text-slate-500">데이터 불러오는 중...</div>
            ) : status ? (
                <div className="space-y-2">
                    {/* H/W Info */}
                    <div className="grid grid-cols-2 gap-2">
                        <div className="p-2 bg-slate-800/40 rounded border border-slate-700/30">
                            <div className="flex items-center gap-1.5 mb-1">
                                <Cpu className="w-3 h-3 text-cyan-400" />
                                <span className="text-[10px] text-slate-400 uppercase">GPU Device</span>
                            </div>
                            <p className="text-xs text-white truncate font-mono" title={status.gpu}>{status.gpu || 'N/A'}</p>
                        </div>
                        <div className="p-2 bg-slate-800/40 rounded border border-slate-700/30">
                            <div className="flex items-center gap-1.5 mb-1">
                                <HardDrive className="w-3 h-3 text-violet-400" />
                                <span className="text-[10px] text-slate-400 uppercase">VRAM Usage</span>
                            </div>
                            <p className="text-xs text-white font-mono">{status.vram_used || '0'} / {status.vram_total || 'N/A'}</p>
                        </div>
                    </div>

                    {/* API Grid */}
                    {status.api_status && (
                        <div className="space-y-1">
                            <p className="text-[10px] text-slate-500 px-1 uppercase font-semibold">API Connections</p>
                            <div className="grid grid-cols-2 gap-2">
                                <ApiItem name="Groq (Llama3)" status={status.api_status.groq} />
                                <ApiItem name="Gemini (Eval)" status={status.api_status.gemini} />
                                <div className="col-span-2">
                                    <ApiItem
                                        name="ElevenLabs"
                                        status={status.api_status.elevenlabs}
                                        usage={status.api_status.elevenlabs_usage}
                                    />
                                </div>
                                <ApiItem name="OpenAI" status={status.api_status.openai} />
                            </div>
                        </div>
                    )}

                    {/* Footer Stats */}
                    <div className="flex justify-between items-center pt-2 mt-1 border-t border-slate-700/50 px-1">
                        <span className="text-[10px] text-slate-500">Active Jobs: {status.active_jobs}</span>
                        <div className="flex items-center gap-1 text-[10px] text-green-400">
                            <Zap className="w-3 h-3" />
                            <span>System Ready</span>
                        </div>
                    </div>
                </div>
            ) : null}
        </div>
    );
}

export default function Layout({ children }) {
    const location = useLocation();
    const [showStatus, setShowStatus] = useState(false);
    const statusButtonRef = useRef(null);
    const { isOnline } = useSystemStatus(false);

    return (
        <div className="min-h-screen flex flex-col">
            <nav className="glass-panel m-4 px-6 py-4 flex items-center justify-between sticky top-4 z-50">
                <Link to="/" className="flex items-center gap-2 no-underline">
                    <div className="p-2 rounded-lg bg-cyan-500/10">
                        <Video className="w-6 h-6 text-cyan-400" />
                    </div>
                    <span className="text-xl font-bold tracking-tight text-white">
                        Video<span className="text-cyan-400">Voice</span>
                    </span>
                </Link>

                <div className="flex items-center gap-6">
                    <div className="relative">
                        <button
                            ref={statusButtonRef}
                            onClick={() => setShowStatus(!showStatus)}
                            className="text-slate-400 hover:text-white transition-colors flex items-center gap-2 text-sm"
                        >
                            <div className="relative">
                                <Activity className="w-4 h-4" />
                                <div className={`absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-500' : 'bg-red-500'}`} />
                            </div>
                            시스템 상태
                        </button>
                        <SystemStatusPopup
                            isOpen={showStatus}
                            onClose={() => setShowStatus(false)}
                            anchorRef={statusButtonRef}
                        />
                    </div>
                    <a
                        href="https://github.com/anthropics/claude-code"
                        target="_blank"
                        rel="noreferrer"
                        className="text-slate-400 hover:text-white transition-colors"
                        title="GitHub"
                    >
                        <Github className="w-5 h-5" />
                    </a>
                </div>
            </nav>

            <main className="container flex-1">
                {children}
            </main>

            <footer className="py-8 text-center text-slate-500 text-sm">
                <p>© 2026 VideoVoice. 로컬 AI 더빙 시스템</p>
            </footer>
        </div>
    );
}
