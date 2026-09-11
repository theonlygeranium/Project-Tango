'use client';

import React, { useEffect, useRef } from 'react';
import { FaReact } from 'react-icons/fa';
import dynamic from 'next/dynamic';
import { useReducedMotion } from 'motion/react';
import { LoopBanner } from '@/components/LoopBanner';
import { MeditationTile } from '@/components/MeditationTile';
import { PersonaSelector } from '@/components/PersonaSelector';
import { ProgramLibrary } from '@/components/ProgramLibrary';
import { Button } from '@/components/ui/button';
import type { BackendLlmModel } from '@/lib/auth';
import type { LlmModelSelectionId } from '@/lib/llm-models';
import { type PersonaId, type TangoPersona } from '@/lib/personas';
import type { Program } from '@/lib/programs';
import { cn } from '@/lib/utils';

// Lazy-load the heavy TippingButton (~15 KB) — deferred until after first paint
const TippingButton = dynamic(
  () => import('@/components/TippingButton').then((m) => m.TippingButton),
  { ssr: false }
);

interface AnimatedSquaresProps {
  direction?: 'diagonal' | 'up' | 'right' | 'down' | 'left';
  speed?: number;
  borderColor?: string;
  squareSize?: number;
  hoverFillColor?: string;
}

const AnimatedSquares: React.FC<AnimatedSquaresProps> = ({
  direction = 'right',
  speed = 0.5,
  squareSize = 40,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const prefersReducedMotion = useReducedMotion();
  const animationState = useRef({
    requestRef: null as number | null,
    gridOffset: { x: 0, y: 0 },
    hoveredSquare: null as { x: number; y: number } | null,
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Read palette from CSS custom properties — single source of truth in globals.css
    const getCanvasPalette = () => {
      const style = getComputedStyle(document.documentElement);
      return {
        border: style.getPropertyValue('--canvas-grid-border').trim(),
        hover: style.getPropertyValue('--canvas-grid-hover').trim(),
        center: style.getPropertyValue('--canvas-grid-center').trim(),
        edge: style.getPropertyValue('--canvas-grid-edge').trim(),
      };
    };

    // ---- State ---------------------------------------------------------------
    let palette = getCanvasPalette();
    let cssWidth = 0;
    let cssHeight = 0;
    let dpr = 1;

    // Re-read palette when the color scheme changes
    const observer = new MutationObserver(() => {
      palette = getCanvasPalette();
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    // ---- Sizing --------------------------------------------------------------
    const resize = () => {
      dpr = window.devicePixelRatio || 1;
      cssWidth = canvas.clientWidth;
      cssHeight = canvas.clientHeight;
      canvas.width = Math.round(cssWidth * dpr);
      canvas.height = Math.round(cssHeight * dpr);
    };
    resize();

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);

    // ---- Mouse / touch interaction ------------------------------------------
    const getGridPos = (clientX: number, clientY: number) => {
      const rect = canvas.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      return { x: Math.floor(x / squareSize), y: Math.floor(y / squareSize) };
    };

    const handleMouseMove = (event: MouseEvent) => {
      const { x, y } = getGridPos(event.clientX, event.clientY);
      animationState.current.hoveredSquare = { x, y };
    };

    const handleTouchMove = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!touch) return;
      const rect = canvas.getBoundingClientRect();
      const mouseX = touch.clientX - rect.left;
      const mouseY = touch.clientY - rect.top;
      animationState.current.hoveredSquare = {
        x: Math.floor(mouseX / squareSize),
        y: Math.floor(mouseY / squareSize),
      };
    };

    const handleMouseLeave = () => {
      animationState.current.hoveredSquare = null;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('touchmove', handleTouchMove, { passive: true });
    window.addEventListener('mouseleave', handleMouseLeave);

    // ---- Animation loop ------------------------------------------------------
    const directions = {
      diagonal: { x: 1, y: 1 },
      up: { x: 0, y: -1 },
      right: { x: 1, y: 0 },
      down: { x: 0, y: 1 },
      left: { x: -1, y: 0 },
    };
    const dir = directions[direction];

    const draw = () => {
      if (!ctx) return;

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, cssWidth, cssHeight);

      const cols = Math.ceil(cssWidth / squareSize) + 1;
      const rows = Math.ceil(cssHeight / squareSize) + 1;
      const { x: offsetX, y: offsetY } = animationState.current.gridOffset;

      for (let row = -1; row < rows; row++) {
        for (let col = -1; col < cols; col++) {
          const px = col * squareSize + (offsetX % squareSize);
          const py = row * squareSize + (offsetY % squareSize);

          // Distance from center for fade effect
          const centerX = cssWidth / 2;
          const centerY = cssHeight / 2;
          const dist = Math.sqrt((px - centerX) ** 2 + (py - centerY) ** 2);
          const maxDist = Math.sqrt(centerX ** 2 + centerY ** 2);
          const alpha = 1 - dist / maxDist;

          // Hover highlight
          const isHovered =
            animationState.current.hoveredSquare?.x === col &&
            animationState.current.hoveredSquare?.y === row;

          ctx.strokeStyle = palette.border || 'rgba(0,0,0,0.1)';
          ctx.lineWidth = 1;

          if (isHovered) {
            ctx.fillStyle = palette.hover || 'rgba(0,0,0,0.05)';
            ctx.fillRect(px, py, squareSize, squareSize);
          }

          ctx.globalAlpha = alpha * 0.5;
          ctx.strokeRect(px, py, squareSize, squareSize);
        }
      }

      ctx.restore();

      // Update grid offset
      if (!prefersReducedMotion) {
        animationState.current.gridOffset.x += dir.x * speed;
        animationState.current.gridOffset.y += dir.y * speed;
      }

      animationState.current.requestRef = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      if (animationState.current.requestRef) {
        cancelAnimationFrame(animationState.current.requestRef);
      }
      observer.disconnect();
      resizeObserver.disconnect();
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [direction, speed, squareSize, prefersReducedMotion]);

  // Canvas is fixed to the viewport so it stays as a background while the page scrolls
  return <canvas ref={canvasRef} className="fixed inset-0 -z-10 h-svh w-full" />;
};

interface WelcomeProps {
  selectedPersonaId: PersonaId;
  personas: TangoPersona[];
  isAdmin?: boolean;
  availableLlmModels?: BackendLlmModel[];
  selectedModels?: Partial<Record<PersonaId, LlmModelSelectionId>>;
  onPersonaChange: (personaId: PersonaId) => void;
  onModelChange?: (personaId: PersonaId, modelId: LlmModelSelectionId) => void;
  onStartCall: () => void;
  onSelectProgram: (program: Program) => void;
  startButtonText: string;
  disabled?: boolean;
}

export const Welcome = React.forwardRef<HTMLDivElement, WelcomeProps>(
  (
    {
      selectedPersonaId,
      personas,
      isAdmin = false,
      availableLlmModels = [],
      selectedModels = {},
      onPersonaChange,
      onModelChange,
      onStartCall,
      onSelectProgram,
      startButtonText,
      disabled = false,
    },
    ref
  ) => {
    function handleTipComplete(): void {
      console.log('Tip animation finished! Thanks for the tip!');
    }

    return (
      <div
        ref={ref}
        inert={disabled}
        className={cn(
          // Use relative + min-h-svh instead of fixed + h-svh + overflow-y-auto.
          // On mobile (especially iOS Safari), position:fixed + overflow-y:auto
          // does not scroll — the content is clipped and unreachable.
          // By using relative positioning and letting the document scroll natively,
          // all content (including the Start Conversation button) is reachable.
          'relative z-10 mx-auto flex min-h-svh flex-col items-center justify-start px-3 pt-[calc(env(safe-area-inset-top)+3.25rem)] pb-[calc(env(safe-area-inset-bottom)+4.5rem)] text-center',
          isAdmin ? 'sm:pt-8 sm:pb-24' : 'sm:py-6'
        )}
      >
        <AnimatedSquares direction="diagonal" speed={0.5} squareSize={42} />

        <div
          className={cn(
            'pointer-events-none relative z-10 flex w-full flex-col items-center gap-3 p-3 sm:p-4',
            isAdmin ? 'max-w-[min(96vw,76rem)] sm:gap-3' : 'max-w-[min(94vw,64rem)] sm:gap-4'
          )}
        >
          <h1
            className={cn(
              'text-foreground font-mono leading-[0.9]',
              isAdmin
                ? 'text-[4.75rem] sm:text-[5.5rem] md:text-[6.5rem] lg:text-[7rem]'
                : 'text-[6rem] sm:text-[7rem] md:text-[8rem] lg:text-[10rem]'
            )}
          >
            TANGO
          </h1>

          <p className="max-w-lg text-sm leading-6 text-sky-500 sm:text-lg sm:leading-7 dark:text-sky-400">
            Choose a voice, then click <span className="font-semibold">Start Conversation</span> to
            begin your chat.
          </p>

          <LoopBanner />

          <div className="pointer-events-auto flex w-full flex-col items-center gap-2">
            <span className="text-foreground/60 font-mono text-xs font-bold uppercase">
              {isAdmin ? 'Persona · Admin model routing' : 'Persona'}
            </span>
            <PersonaSelector
              selectedPersonaId={selectedPersonaId}
              personas={personas}
              isAdmin={isAdmin}
              availableLlmModels={availableLlmModels}
              selectedModels={selectedModels}
              onPersonaChange={onPersonaChange}
              onModelChange={onModelChange}
              disabled={disabled}
            />
          </div>

          <div className="pointer-events-auto flex w-full flex-col items-center gap-2">
            <span className="text-foreground/60 font-mono text-xs font-bold uppercase">
              Meditation
            </span>
            <div className="grid w-full max-w-4xl grid-cols-1 gap-2 sm:grid-cols-2">
              <MeditationTile />
            </div>
          </div>

          <ProgramLibrary
            personas={personas}
            disabled={disabled}
            onSelectProgram={onSelectProgram}
          />

          <Button
            variant="primary"
            size="lg"
            onClick={onStartCall}
            className="text-primary-foreground/80 hover:text-primary-foreground pointer-events-auto min-h-12 w-72 max-w-full font-sans text-[0.85rem] transition-colors"
            disabled={disabled}
          >
            {startButtonText}
          </Button>
        </div>

        <div
          className={cn(
            'pointer-events-none flex w-full max-w-prose flex-col items-center gap-1 px-4 text-center text-xs',
            isAdmin ? 'relative z-10 mt-1 pb-4' : 'relative z-10 mt-2 pb-6'
          )}
        >
          <p className="font-medium text-sky-500 dark:text-sky-400">
            Developed by{' '}
            <a
              href="https://edstratumlabs.ai/"
              target="_blank"
              rel="noopener noreferrer"
              className="pointer-events-auto underline underline-offset-4 hover:text-sky-300 dark:hover:text-sky-300"
            >
              EdStratum Labs
            </a>{' '}
            &mdash; Proprietary & Confidential
          </p>
          <p className="text-foreground/60">
            Project Tango uses{' '}
            <a
              target="_blank"
              rel="noopener noreferrer"
              href="https://livekit.io"
              className="hover:text-foreground/80 pointer-events-auto underline"
            >
              LiveKit
            </a>
            .
          </p>
        </div>

        {!isAdmin && (
          <TippingButton
            onTip={handleTipComplete}
            coinIcon={<FaReact size="100%" color="currentColor" />}
            instructionText="Click to show appreciation"
          >
            Support Creator
          </TippingButton>
        )}
      </div>
    );
  }
);

Welcome.displayName = 'Welcome';
