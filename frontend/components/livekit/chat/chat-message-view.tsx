'use client';

import { type RefObject, useCallback, useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';

const STICK_TO_BOTTOM_THRESHOLD = 80;

export function useAutoScroll(scrollContentContainerRef: RefObject<Element | null>) {
  const stickToBottomRef = useRef(true);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const { scrollingElement } = document;
    if (!scrollingElement) return;

    scrollingElement.scrollTo({
      top: scrollingElement.scrollHeight,
      behavior,
    });
  }, []);

  // Track whether the user is near the bottom of the page.
  // If they've scrolled up, we don't force-scroll down.
  useEffect(() => {
    function onScroll() {
      const { scrollingElement } = document;
      if (!scrollingElement) return;

      const distanceFromBottom =
        scrollingElement.scrollHeight - scrollingElement.scrollTop - scrollingElement.clientHeight;

      stickToBottomRef.current = distanceFromBottom <= STICK_TO_BOTTOM_THRESHOLD;
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // ResizeObserver: scroll to bottom when content grows, but only if the
  // user hasn't manually scrolled away from the bottom.
  useEffect(() => {
    const container = scrollContentContainerRef.current;
    if (!container) return;

    const resizeObserver = new ResizeObserver(() => {
      if (stickToBottomRef.current) {
        scrollToBottom('smooth');
      }
    });

    resizeObserver.observe(container);
    scrollToBottom('auto');

    return () => resizeObserver.disconnect();
  }, [scrollContentContainerRef, scrollToBottom]);
}

interface ChatProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode;
  className?: string;
}

export const ChatMessageView = ({ className, children, ...props }: ChatProps) => {
  const scrollContentRef = useRef<HTMLDivElement>(null);

  useAutoScroll(scrollContentRef);

  return (
    <div ref={scrollContentRef} className={cn('flex flex-col justify-end', className)} {...props}>
      {children}
    </div>
  );
};
