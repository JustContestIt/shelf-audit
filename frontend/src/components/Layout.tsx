import { useEffect } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync, useInterval } from '../hooks/useAsync';
import { usePending } from '../hooks/pending';
import { fmtInt } from '../lib/format';
import { Logo } from './Logo';

function HealthLine() {
  const health = useAsync(() => api.health(), []);
  useInterval(health.reload, 60_000);
  const h = health.data;
  if (!h && health.error) {
    return (
      <span>
        <span className="dot bad" aria-hidden="true" />
        API недоступен: {health.error}
      </span>
    );
  }
  if (!h) return <span className="faint">Проверка API…</span>;
  return (
    <>
      <span>
        <span className={`dot ${h.ok && !health.error ? 'ok' : 'bad'}`} aria-hidden="true" />
        API {h.version}
        {health.error ? ' (нет связи)' : ''}
      </span>
      <span>LLM: {h.llm_mode}</span>
      <span>
        промпт <span className="mono">{h.prompt}</span>
        {h.verify_prompt ? (
          <>
            {' '}
            / проход 2 <span className="mono">{h.verify_prompt}</span>
          </>
        ) : null}
      </span>
      <span>эталонов в индексе: {fmtInt(h.refs_indexed)}</span>
    </>
  );
}

export function Layout() {
  const { count, refresh } = usePending();
  const location = useLocation();

  useEffect(() => {
    refresh();
  }, [location.pathname, refresh]);

  return (
    <div className="app">
      <a href="#main" className="skip-link">
        Перейти к содержимому
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">
            <Logo />
            <span>Аудит полки</span>
          </Link>
          <nav className="nav" aria-label="Разделы">
            <NavLink to="/upload">Загрузить фото</NavLink>
            <NavLink to="/queue">
              Очередь на проверку
              {count ? (
                <span className="count-badge" aria-label={`ждут проверки: ${count}`}>
                  {count}
                </span>
              ) : null}
            </NavLink>
            <NavLink to="/reports">
              Отчёты
            </NavLink>
            <NavLink to="/evals">Evals</NavLink>
            <NavLink to="/about">О системе</NavLink>
          </nav>
        </div>
      </header>
      <main id="main" className="container" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
        <div className="footer-inner small">
          <HealthLine />
        </div>
      </footer>
    </div>
  );
}
