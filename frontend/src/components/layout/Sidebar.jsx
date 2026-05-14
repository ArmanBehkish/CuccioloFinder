import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { RiHomeHeartFill, RiMagicFill } from 'react-icons/ri';
import { BsSearchHeartFill } from 'react-icons/bs';
import { ImStatsDots } from 'react-icons/im';
import { LuMessageSquare } from 'react-icons/lu';
import { PiDogFill } from 'react-icons/pi';
import './Sidebar.css';

function Sidebar() {
  const [mobileOpen, setMobileOpen] = useState(false);

  const closeMobile = () => setMobileOpen(false);

  return (
    <>
      {/* Mobile top bar */}
      <div className="mobile-header">
        <h1>CuccioloFinder</h1>
        <button
          className="hamburger-btn"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle navigation"
        >
          {mobileOpen ? '\u2715' : '\u2630'}
        </button>
      </div>

      {/* Overlay */}
      <div
        className={`sidebar-overlay ${mobileOpen ? 'open' : ''}`}
        onClick={closeMobile}
      />

      {/* Sidebar */}
      <nav className={`sidebar ${mobileOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <div className="logo-icon"><PiDogFill /></div>
          <h1>CuccioloFinder</h1>
          <div className="tagline">Find a puppy you love</div>
        </div>

        <ul className="sidebar-nav">
          <li>
            <NavLink to="/" end onClick={closeMobile}>
              <span className="nav-icon nav-icon-lg"><RiHomeHeartFill /></span>
              Home
            </NavLink>
          </li>
          <li>
            <NavLink to="/filter" onClick={closeMobile}>
              <span className="nav-icon"><BsSearchHeartFill /></span>
              Search & Filter
            </NavLink>
          </li>
          <li>
            <NavLink to="/search" onClick={closeMobile}>
              <span className="nav-icon"><RiMagicFill /></span>
              Smart Search
            </NavLink>
          </li>
          <li>
            <NavLink to="/stats" onClick={closeMobile}>
              <span className="nav-icon"><ImStatsDots /></span>
              Statistics
            </NavLink>
          </li>
          <li>
            <NavLink to="/contact" onClick={closeMobile}>
              <span className="nav-icon nav-icon-lg"><LuMessageSquare /></span>
              Contact
            </NavLink>
          </li>
        </ul>

        <div className="sidebar-footer">
          CuccioloFinder v0.1
        </div>
      </nav>
    </>
  );
}

export default Sidebar;
