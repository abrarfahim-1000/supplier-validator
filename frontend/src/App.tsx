import { IconBrandGithubFilled, IconBrandLinkedinFilled } from '@tabler/icons-react'
import { CheckerPage } from './components/checker-page'
import { useServiceHealth } from './workflow/health'
import type { ServiceHealth } from './workflow/health'

export default function App() {
  const service = useServiceHealth()

  return (
    <div className="shell">
      <header className="masthead">
        <div className="wrap masthead__inner">
          <p className="wordmark">
            <span className="wordmark__rule" aria-hidden="true" />
            Supplier Document Checker
          </p>
          <ServiceStatus service={service} />
        </div>
      </header>

      <main className="page">
        <div className="wrap">
          <CheckerPage service={service} />
        </div>
      </main>

      <footer className="site-footer">
        <div className="wrap site-footer__inner">
          <nav className="site-footer__socials" aria-label="Social profiles">
            <a
              className="site-footer__social-link"
              href="https://github.com/abrarfahim-1000"
              target="_blank"
              rel="noreferrer"
              aria-label="GitHub"
              title="GitHub"
            >
              <IconBrandGithubFilled size={20} aria-hidden="true" />
            </a>
            <a
              className="site-footer__social-link"
              href="https://www.linkedin.com/in/abrar-fahim-5b370934b/"
              target="_blank"
              rel="noreferrer"
              aria-label="LinkedIn"
              title="LinkedIn"
            >
              <IconBrandLinkedinFilled size={20} aria-hidden="true" />
            </a>
          </nav>
        </div>
      </footer>
    </div>
  )
}

function ServiceStatus({ service }: { service: ServiceHealth }) {
  const label =
    service.state === 'ready'
      ? 'service ready'
      : service.state === 'starting'
        ? 'waking service'
        : 'service unreachable'

  return (
    <p className="service" data-state={service.state} aria-live="polite">
      <span className="service__dot" aria-hidden="true" />
      <span>{label}</span>
      {service.state === 'down' ? (
        <button type="button" className="service__retry" onClick={service.retry}>
          retry
        </button>
      ) : null}
    </p>
  )
}
