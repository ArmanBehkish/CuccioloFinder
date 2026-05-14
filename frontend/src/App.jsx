import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './components/layout/Sidebar';
import 'bootstrap/dist/css/bootstrap.min.css';
import './App.css';

function App() {
  const location = useLocation();
  const isHome = location.pathname === '/' || location.pathname === '';

  // React Router doesn't reset scroll on route changes. Without this,
  // navigating from the bottom of one page (e.g. the homepage donate banner)
  // lands the next page already scrolled down.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <div className="app-layout">
      <Sidebar />
      <main className={`main-content ${isHome ? '' : 'main-content-padded'}`}>
        <Outlet />
      </main>
    </div>
  );
}

export default App;
