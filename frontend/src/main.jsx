import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import App from './App';
import HomePage from './components/pages/HomePage';
import FilterSearchPage from './components/pages/FilterSearchPage';
import NaturalSearchPage from './components/pages/NaturalSearchPage';
import StatsPage from './components/pages/StatsPage';
import DogDetailPage from './components/pages/DogDetailPage';
import ContactPage from './components/pages/ContactPage';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter basename="/cucciolofinder">
      <Routes>
        <Route element={<App />}>
          <Route index element={<HomePage />} />
          <Route path="filter" element={<FilterSearchPage />} />
          <Route path="search" element={<NaturalSearchPage />} />
          <Route path="stats" element={<StatsPage />} />
          <Route path="dogs/:id" element={<DogDetailPage />} />
          <Route path="contact" element={<ContactPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
