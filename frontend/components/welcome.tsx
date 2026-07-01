'use client';

import React, { useEffect, useRef } from 'react';
import { FaReact } from 'react-icons/fa';
import { LlmModelSelector } from '@/components/LlmModelSelector';
import { LoopBanner } from '@/components/LoopBanner';
import { PersonaSelector } from '@/components/PersonaSelector';
import { TippingButton } from '@/components/TippingButton';
import { Button } from '@/components/ui/button';
import { type LlmModelSelectionId } from '@/lib/llm-models';
import { type PersonaId } from '@/lib/personas';

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
  borderColor = '#333',
  squareSize = 40,
  hoverFillColor = '#222',
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
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

    const getCanvasPalette = () => {
      const isDark = document.documentElement.classList.contains('dark');

      if (isDark) {
        return {
          border: borderColor,
          hover: hoverFillColor,
          center: 'rgba(18, 18, 18, 0)',
          edge: 'rgba(18, 18, 18, 1)',
        };
      }

      return {
        border: 'rgba(0, 44, 242, 0.16)',
        hover: 'rgba(0, 44, 242, 0.06)',
        center: 'rgba(249, 249, 246, 0)',
        edge: 'rgba(249, 249, 246, 1)',
      };
    };

    const resizeCanvas = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };

    const drawGrid = () => {
      const state = animationState.current;
      const palette = getCanvasPalette();
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (let x = 0; x < canvas.width + squareSize; x += squareSize) {
        for (let y = 0; y < canvas.height + squareSize; y += squareSize) {
          const squareX = x - (state.gridOffset.x % squareSize);
          const squareY = y - (state.gridOffset.y % squareSize);

          const isHovered =
            state.hoveredSquare &&
            Math.floor(x / squareSize) === state.hoveredSquare.x &&
            Math.floor(y / squareSize) === state.hoveredSquare.y;

          if (isHovered) {
            ctx.fillStyle = palette.hover;
            ctx.fillRect(squareX, squareY, squareSize, squareSize);
          }

          ctx.strokeStyle = palette.border;
          ctx.strokeRect(squareX, squareY, squareSize, squareSize);
        }
      }

      const gradient = ctx.createRadialGradient(
        canvas.width / 2,
        canvas.height / 2,
        0,
        canvas.width / 2,
        canvas.height / 2,
        Math.max(canvas.width, canvas.height) / 1.5
      );
      gradient.addColorStop(0, palette.center);
      gradient.addColorStop(1, palette.edge);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    };

    const updateAnimation = () => {
      const state = animationState.current;
      const effectiveSpeed = Math.max(speed, 0.1);
      state.gridOffset.x = (state.gridOffset.x - effectiveSpeed + squareSize) % squareSize;
      drawGrid();
      state.requestRef = requestAnimationFrame(updateAnimation);
    };

    const handleMouseMove = (event: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;
      const state = animationState.current;

      const hoveredX = Math.floor((mouseX + state.gridOffset.x) / squareSize);
      const hoveredY = Math.floor((mouseY + state.gridOffset.y) / squareSize);

      state.hoveredSquare = { x: hoveredX, y: hoveredY };
    };

    const handleMouseLeave = () => {
      animationState.current.hoveredSquare = null;
    };

    const handleTouchMove = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!touch) return;
      const rect = canvas.getBoundingClientRect();
      const mouseX = touch.clientX - rect.left;
      const mouseY = touch.clientY - rect.top;
      const state = animationState.current;
      state.hoveredSquare = {
        x: Math.floor((mouseX + state.gridOffset.x) / squareSize),
        y: Math.floor((mouseY + state.gridOffset.y) / squareSize),
      };
    };

    resizeCanvas();
    updateAnimation();
    window.addEventListener('resize', resizeCanvas);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('touchmove', handleTouchMove, { passive: true });
    window.addEventListener('mouseleave', handleMouseLeave);

    const state = animationState.current;
    return () => {
      if (state.requestRef) {
        cancelAnimationFrame(state.requestRef);
      }
      window.removeEventListener('resize', resizeCanvas);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [direction, speed, borderColor, squareSize, hoverFillColor]);

  return <canvas ref={canvasRef} className="absolute inset-0 -z-10 h-full w-full" />;
};

interface WelcomeProps {
  disabled: boolean;
  startButtonText: string;
  selectedPersonaId: PersonaId;
  selectedLlmModelId: LlmModelSelectionId;
  onPersonaChange: (personaId: PersonaId) => void;
  onLlmModelChange: (llmModelId: LlmModelSelectionId) => void;
  onStartCall: () => void;
}

export const Welcome = React.forwardRef<HTMLDivElement, WelcomeProps>(
  (
    {
      disabled,
      startButtonText,
      selectedPersonaId,
      selectedLlmModelId,
      onPersonaChange,
      onLlmModelChange,
      onStartCall,
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
        className="fixed inset-0 z-10 mx-auto flex h-svh flex-col items-center justify-start overflow-y-auto px-3 pt-[calc(env(safe-area-inset-top)+3.25rem)] pb-[calc(env(safe-area-inset-bottom)+4.5rem)] text-center sm:justify-center sm:overflow-hidden sm:p-0"
      >
        <AnimatedSquares
          direction="diagonal"
          speed={0.5}
          borderColor="#333"
          squareSize={42}
          hoverFillColor="#222"
        />

        <div className="pointer-events-none relative z-10 flex w-full max-w-[min(94vw,64rem)] flex-col items-center gap-3 p-3 sm:gap-4 sm:p-4">
          <h1 className="text-foreground font-mono text-[6rem] leading-[0.9] sm:text-[7rem] md:text-[8rem] lg:text-[10rem]">
            TANGO
          </h1>

          <p className="max-w-lg text-sm leading-6 text-sky-500 sm:text-lg sm:leading-7 dark:text-sky-400">
            Choose a voice, then click <span className="font-semibold">Start Conversation</span> to
            begin your chat.
          </p>

          <LoopBanner />

          <div className="pointer-events-auto flex w-full flex-col items-center gap-2">
            <span className="text-foreground/60 font-mono text-xs font-bold uppercase">
              Persona
            </span>
            <PersonaSelector
              selectedPersonaId={selectedPersonaId}
              onPersonaChange={onPersonaChange}
              disabled={disabled}
            />
          </div>

          <div className="pointer-events-auto flex w-full flex-col items-center gap-2">
            <span className="text-foreground/60 font-mono text-xs font-bold uppercase">Model</span>
            <LlmModelSelector
              selectedLlmModelId={selectedLlmModelId}
              onLlmModelChange={onLlmModelChange}
              disabled={disabled}
            />
          </div>

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

        <div className="pointer-events-none fixed bottom-6 left-1/2 flex w-full max-w-prose -translate-x-1/2 flex-col items-center gap-1 px-4 text-center text-xs">
          <p className="font-medium text-sky-500 dark:text-sky-400">
            Developed by Geronimo AI &mdash; Proprietary & Confidential
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

        <TippingButton
          onTip={handleTipComplete}
          coinIcon={<FaReact size="100%" color="currentColor" />}
          instructionText="Click to show appreciation"
        >
          Support Creator
        </TippingButton>
      </div>
    );
  }
);

Welcome.displayName = 'Welcome';
