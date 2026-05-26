import { Link } from 'react-router-dom';
import { BsSearchHeartFill } from 'react-icons/bs';
import { RiMagicFill } from 'react-icons/ri';
import { ImStatsDots } from 'react-icons/im';
import { PiDogFill, PiHeartFill } from 'react-icons/pi';
import './HomePage.css';

function HomePage() {
  return (
    <div className="home-page">
      {/* Hero section with video background */}
      <section className="hero">
        <video
          className="hero-video"
          autoPlay
          muted
          loop
          playsInline
          poster=""
        >
          <source src={`${import.meta.env.BASE_URL}hero_g.mp4`} type="video/mp4" />
        </video>
        <div className="hero-overlay" />
        <div className="hero-content">
          <div className="hero-title-row">
            <PiDogFill className="hero-logo" />
            <div>
              <h1>CuccioloFinder</h1>
              <p>Helping shelter dogs in Torino find loving homes</p>
            </div>
          </div>
        </div>
      </section>

      {/* About section */}
      <section className="home-section">
        <h2>What is CuccioloFinder?</h2>
        <p>
          CuccioloFinder aggregates adoptable dogs from shelters across the Torino
          and Piemonte region. We automatically collect listings, translate descriptions
          from Italian to English, and use machine learning to identify breeds and
          match you with your perfect companion.
        </p>
      </section>

      {/* Features / how to use */}
      <section className="home-section">
        <h2>How to Find Your Dog</h2>
        <div className="feature-cards">
          <Link to="/filter" className="feature-card">
            <div className="feature-icon"><BsSearchHeartFill /></div>
            <h3>Search & Filter</h3>
            <p>
              Search by size, breed, age, gender, and more.
            </p>
          </Link>

          <Link to="/search" className="feature-card">
            <div className="feature-icon"><RiMagicFill /></div>
            <h3>Smart Search</h3>
            <p>
              Describe your ideal dog and let AI find the best matches.
            </p>
          </Link>

          <Link to="/stats" className="feature-card">
            <div className="feature-icon"><ImStatsDots /></div>
            <h3>Statistics</h3>
            <p>
              Explore breed distributions, shelter trends, and more.
            </p>
          </Link>
        </div>
      </section>

      {/* Shelters */}
      <section className="home-section">
        <h2>Our Shelter Partners</h2>
        <p>
          We collect data from 4 shelters and rescue organizations in the
          Torino area, updated every 12 hours:
        </p>
        <ul className="shelter-list">
          <li><a href="https://www.quattrozampeinfamiglia.it" target="_blank" rel="noopener noreferrer">Quattro Zampe in Famiglia</a></li>
          {/* Hidden per shelter request — paired with DISABLED_SHELTERS in src/cucciolofinder/config.py.
              <li><a href="https://alberodimais.it" target="_blank" rel="noopener noreferrer">Albero di Mais</a></li>
          */}
          <li><a href="https://www.empethy.it/organizzazioni/rifugio-impronta-creativa-torino" target="_blank" rel="noopener noreferrer">Empethy &mdash; Rifugio Impronta Creativa Torino</a></li>
          <li><a href="https://www.voltoweb.it/enpasezionetorino/" target="_blank" rel="noopener noreferrer">ENPA Sezione Torino</a></li>
          <li><a href="https://canileoasi.it" target="_blank" rel="noopener noreferrer">Canile Oasi</a></li>
        </ul>
      </section>

      {/* Donate banner — sits at the bottom so visitors only see it after
       * they've read the whole page. Links to the Contact page where the
       * full donate context + Ko-fi button live. */}
      <Link to="/contact" className="home-donate-banner">
        <PiHeartFill className="home-donate-banner-icon" />
        <span>If you find CuccioloFinder useful, consider buying me a coffee</span>
      </Link>
    </div>
  );
}

export default HomePage;
