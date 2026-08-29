import { useMediaQuery } from '@mantine/hooks';
import { isForcedMobile } from '../pwa/desktopSiteGuard';

/**
 * Drop-in replacement for useMediaQuery('(max-width: …)') mobile checks.
 * Returns true when the width query matches OR when the desktop-site guard
 * detected Chrome's "Desktop site" mode inside the installed PWA (where the
 * layout viewport is ~980px and width queries would wrongly report desktop).
 */
export function useIsMobile(query) {
  const queryMatches = useMediaQuery(query);
  return isForcedMobile() || queryMatches;
}
