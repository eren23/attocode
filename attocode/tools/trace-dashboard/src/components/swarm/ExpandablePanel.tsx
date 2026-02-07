/**
 * ExpandablePanel - Wraps any panel with a hover-to-reveal expand button.
 * Clicking expand opens the panel content in a full-screen modal overlay.
 *
 * When expanded, a `data-expanded` attribute is set on the content wrapper.
 * Child panels use the `max-h-*` Tailwind class to cap their scroll area in
 * the normal grid layout.  Inside the modal we override these via the
 * `[data-expanded] *` selector so children stretch to fill the viewport.
 */

import { useState, useEffect, useCallback } from 'react';

interface ExpandablePanelProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

export function ExpandablePanel({ title, children, className }: ExpandablePanelProps) {
  const [expanded, setExpanded] = useState(false);

  const handleClose = useCallback(() => setExpanded(false), []);

  // Close on ESC key
  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [expanded, handleClose]);

  return (
    <>
      <div className={`relative group ${className ?? ''}`}>
        {/* Expand button - visible on hover */}
        <button
          onClick={() => setExpanded(true)}
          className="absolute top-3 right-3 z-10 opacity-0 group-hover:opacity-100 transition-opacity
            p-1.5 rounded-md bg-gray-800/80 hover:bg-gray-700 text-gray-400 hover:text-white
            border border-gray-700/50"
          title={`Expand ${title}`}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 3 21 3 21 9" />
            <polyline points="9 21 3 21 3 15" />
            <line x1="21" y1="3" x2="14" y2="10" />
            <line x1="3" y1="21" x2="10" y2="14" />
          </svg>
        </button>
        {children}
      </div>

      {/* Full-screen modal */}
      {expanded && (
        <div
          className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6"
          onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
        >
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-full h-full overflow-hidden p-6 flex flex-col">
            <div className="flex items-center justify-between mb-4 flex-shrink-0">
              <h2 className="text-lg font-semibold text-white">{title}</h2>
              <button
                onClick={handleClose}
                className="p-1.5 rounded-md hover:bg-gray-800 text-gray-400 hover:text-white transition-colors"
                title="Close (ESC)"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            {/*
              expanded-panel-content: the inline style overrides all max-h-*
              constraints on children so they fill the modal viewport.
            */}
            <div
              className="flex-1 min-h-0 flex flex-col"
              ref={(el) => {
                if (!el) return;
                // Override max-height on the direct child panel and its scroll containers
                const child = el.firstElementChild as HTMLElement | null;
                if (child) {
                  child.style.height = '100%';
                  child.style.maxHeight = '100%';
                  child.style.display = 'flex';
                  child.style.flexDirection = 'column';
                  // Find scroll containers inside and remove their max-h cap
                  const scrollAreas = child.querySelectorAll<HTMLElement>('[class*="max-h-"]');
                  for (const area of scrollAreas) {
                    area.style.maxHeight = 'none';
                    area.style.flex = '1 1 0%';
                  }
                  // Also handle overflow-auto containers that use flex-1
                  const flexAreas = child.querySelectorAll<HTMLElement>('.overflow-y-auto, .overflow-auto');
                  for (const area of flexAreas) {
                    area.style.maxHeight = 'none';
                    area.style.flex = '1 1 0%';
                  }
                }
              }}
            >
              {children}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
