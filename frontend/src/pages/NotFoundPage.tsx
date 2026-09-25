import { Link } from 'react-router-dom';
import { usePageTitle } from '../hooks/usePageTitle';

export function NotFoundPage() {
  usePageTitle('Страница не найдена');
  return (
    <div className="card">
      <div className="empty">
        <h1 style={{ marginBottom: 8 }}>Страница не найдена</h1>
        <p>
          <Link to="/queue">Перейти к очереди на проверку</Link>
        </p>
      </div>
    </div>
  );
}
