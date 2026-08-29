import { useState } from 'react'
import { Alert, CloseButton } from '@mantine/core'
import { MdOutlineDesktopWindows } from 'react-icons/md'
import { isForcedMobile } from './desktopSiteGuard'

const DISMISS_KEY = 'desktop_site_notice_dismissed'

/**
 * Shown only when desktopSiteGuard is compensating for Chrome's "Desktop
 * site" setting inside the installed PWA. The zoom fix keeps the app usable,
 * but unchecking the setting in Chrome is the real, durable fix — point at it.
 */
export default function DesktopSiteNotice() {
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem(DISMISS_KEY) === '1'
  )

  if (!isForcedMobile() || dismissed) return null

  const dismiss = () => {
    sessionStorage.setItem(DISMISS_KEY, '1')
    setDismissed(true)
  }

  return (
    <Alert
      icon={<MdOutlineDesktopWindows size={16} />}
      color="yellow"
      radius={0}
      py={6}
      styles={{
        root: {
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 3000,
          // Mantine's yellow "light" variant is translucent — the AppShell
          // header bleeds through a fixed banner, so paint it opaque.
          background: '#fff3bf',
          borderBottom: '1px solid #ffe066'
        },
        message: { fontSize: 12, paddingRight: 28 }
      }}
    >
      Simulating mobile view — uncheck ⋮ → &quot;Desktop site&quot; in Chrome to fix.
      <CloseButton size="sm" onClick={dismiss} style={{ position: 'absolute', top: 6, right: 6 }} />
    </Alert>
  )
}
