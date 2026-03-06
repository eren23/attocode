/**
 * FlowTimeline - Horizontal timeline for post-mortem replay.
 *
 * Shows session duration with a scrubber, play/pause, speed controls,
 * and data flow event dots along the timeline.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import type { DataFlow } from '../../lib/agent-graph-types';
import { FLOW_TYPE_STYLES } from '../../lib/agent-graph-types';
import { useAnimationLoop } from '../../hooks/useAnimationLoop';

interface FlowTimelineProps {
  flows: DataFlow[];
  /** Session start timestamp (ms) */
  startTime: number;
  /** Session end timestamp (ms) */
  endTime: number;
  /** Current replay timestamp */
  currentTime: number;
  /** Called when user scrubs or playback advances */
  onTimeChange: (time: number) => void;
  /** Whether timeline is currently playing */
  playing: boolean;
  onPlayPause: () => void;
  /** Playback speed multiplier */
  speed: number;
  onSpeedChange: (speed: number) => void;
}

const SPEED_OPTIONS = [1, 2, 5, 10];

function formatTimestamp(ms: number): string {
  const sec = Math.floor(ms / 1000);
  const min = Math.floor(sec / 60);
  const s = sec % 60;
  if (min > 0) {
    return `${min}:${s.toString().padStart(2, '0')}`;
  }
  return `${s}s`;
}

export function FlowTimeline({
  flows,
  startTime,
  endTime,
  currentTime,
  onTimeChange,
  playing,
  onPlayPause,
  speed,
  onSpeedChange,
}: FlowTimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const duration = Math.max(endTime - startTime, 1);
  const progress = Math.max(0, Math.min(1, (currentTime - startTime) / duration));

  // Advance playback with requestAnimationFrame
  useAnimationLoop(
    (deltaMs) => {
      const advance = deltaMs * speed;
      const newTime = Math.min(currentTime + advance, endTime);
      onTimeChange(newTime);
      if (newTime >= endTime) {
        onPlayPause(); // auto-pause at end
      }
    },
    playing && !dragging
  );

  // Handle scrubbing via mouse/touch
  const handleScrub = useCallback(
    (clientX: number) => {
      if (!trackRef.current) return;
      const rect = trackRef.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      onTimeChange(startTime + ratio * duration);
    },
    [startTime, duration, onTimeChange]
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      setDragging(true);
      handleScrub(e.clientX);
    },
    [handleScrub]
  );

  useEffect(() => {
    if (!dragging) return;
    const handleMove = (e: MouseEvent) => handleScrub(e.clientX);
    const handleUp = () => setDragging(false);
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [dragging, handleScrub]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
      <div className="flex items-center gap-3">
        {/* Play/Pause button */}
        <button
          onClick={onPlayPause}
          className="w-8 h-8 flex items-center justify-center rounded-full bg-gray-800 hover:bg-gray-700 text-white transition-colors shrink-0"
        >
          {playing ? (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="4" width="4" height="16" />
              <rect x="14" y="4" width="4" height="16" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <polygon points="5,3 19,12 5,21" />
            </svg>
          )}
        </button>

        {/* Current time */}
        <span className="text-xs text-gray-400 font-mono w-12 text-right shrink-0">
          {formatTimestamp(currentTime - startTime)}
        </span>

        {/* Timeline track */}
        <div
          ref={trackRef}
          className="flex-1 relative h-6 cursor-pointer select-none"
          onMouseDown={handleMouseDown}
        >
          {/* Background track */}
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 bg-gray-800 rounded-full" />

          {/* Progress fill */}
          <div
            className="absolute top-1/2 -translate-y-1/2 h-1.5 bg-blue-600 rounded-full"
            style={{ width: `${progress * 100}%` }}
          />

          {/* Data flow event dots */}
          {flows.map((flow) => {
            const flowProgress = (flow.timestamp - startTime) / duration;
            if (flowProgress < 0 || flowProgress > 1) return null;
            const style = FLOW_TYPE_STYLES[flow.type];
            return (
              <div
                key={flow.id}
                className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full"
                style={{
                  left: `${flowProgress * 100}%`,
                  backgroundColor: style.color,
                  opacity: flow.timestamp <= currentTime ? 1 : 0.3,
                }}
                title={`${style.label}: ${flow.payload.summary}`}
              />
            );
          })}

          {/* Scrubber handle */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full shadow-lg border-2 border-blue-500 -ml-1.5"
            style={{ left: `${progress * 100}%` }}
          />
        </div>

        {/* Duration */}
        <span className="text-xs text-gray-500 font-mono w-12 shrink-0">
          {formatTimestamp(duration)}
        </span>

        {/* Speed selector */}
        <div className="flex items-center gap-1 shrink-0">
          {SPEED_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSpeedChange(s)}
              className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                speed === s
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-white hover:bg-gray-700'
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
