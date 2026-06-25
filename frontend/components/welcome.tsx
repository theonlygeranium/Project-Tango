'use client';

import React, { useEffect, useRef } from 'react';
import { FaReact } from 'react-icons/fa';
import { PersonaSelector } from '@/components/PersonaSelector';
import { TippingButton } from '@/components/TippingButton';
import { Button } from '@/components/ui/button';
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

    // This event listener is now on the window, so it works everywhere
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

    resizeCanvas();
    updateAnimation();
    window.addEventListener('resize', resizeCanvas);
    // Attach mouse move to the window, not the canvas
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseleave', handleMouseLeave);

    const state = animationState.current;
    return () => {
      if (state.requestRef) {
        cancelAnimationFrame(state.requestRef);
      }
      window.removeEventListener('resize', resizeCanvas);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [direction, speed, borderColor, squareSize, hoverFillColor]);

  return <canvas ref={canvasRef} className="absolute inset-0 -z-10 h-full w-full" />;
};

interface WelcomeProps {
  disabled: boolean;
  startButtonText: string;
  selectedPersonaId: PersonaId;
  onPersonaChange: (personaId: PersonaId) => void;
  onStartCall: () => void;
}

export const Welcome = React.forwardRef<HTMLDivElement, WelcomeProps>(
  ({ disabled, startButtonText, selectedPersonaId, onPersonaChange, onStartCall }, ref) => {
    function handleTipComplete(): void {
      // Show a thank you message or perform any desired action after tipping
      console.log('Tip animation finished! Thanks for the tip!');
    }

    return (
      <div
        ref={ref}
        inert={disabled}
        className="fixed inset-0 z-10 mx-auto flex h-svh flex-col items-center justify-center text-center"
      >
        <AnimatedSquares
          direction="diagonal"
          speed={0.5}
          borderColor="#333"
          squareSize={42}
          hoverFillColor="#222"
        />

        <div className="pointer-events-none relative z-10 flex max-w-[min(94vw,48rem)] flex-col items-center gap-4 p-4">
          <h1 className="text-foreground font-mono text-5xl leading-none sm:text-7xl md:text-[8rem] lg:text-[10rem]">
            TANGO
          </h1>

          <p className="text-foreground/80 max-w-lg text-base leading-7 sm:text-lg">
            Choose a voice, then begin a thoughtful Project Tango session.
          </p>

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

          <Button
            variant="primary"
            size="lg"
            onClick={onStartCall}
            className="text-primary-foreground/80 hover:text-primary-foreground pointer-events-auto min-h-11 w-64 font-sans text-[0.85rem] transition-colors"
            disabled={disabled}
          >
            {startButtonText}
          </Button>
        </div>

        <p className="text-foreground/60 pointer-events-none fixed bottom-6 left-1/2 w-full max-w-prose -translate-x-1/2 text-xs">
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
