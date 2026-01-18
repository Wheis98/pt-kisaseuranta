import { BrowserRouter, Routes, Route } from 'react-router';
import { NavLink } from 'react-router';
import { useState } from 'react';
import AppBar from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Menu from '@mui/material/Menu';
import HomeIcon from '@mui/icons-material/Home';
import SettingsIcon from '@mui/icons-material/Settings';
import HomeUI from './pages/HomeUI';
import ReaderUI from './pages/ReaderUI';
import AdminUI from './pages/AdminUI';
import './App.css'

const App = () => {
  const [anchorEl, setAnchorEl] = useState(null);

  const handleSettings = (event) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  return (
    <BrowserRouter>
      {/* Navigation */}
      <AppBar>
        <Toolbar>
          <NavLink to="/">
            <IconButton
              size="large"
              edge="start"
              aria-label="home"
              sx={{ mr: 2 }}
            >
              <HomeIcon />
            </IconButton>
          </NavLink>
          <IconButton
            size="large"
            edge="end"
            aria-label="settings"
            aria-controls="settings-popup"
            aria-haspopup="true"
            sx={{ mr: 2 }}
            onClick={handleSettings}
          >
            <SettingsIcon />
          </IconButton>
          <Menu
            id="settings-popup"
            anchorEl={anchorEl}
            anchorOrigin={{
              vertical: 'top',
              horizontal: 'right',
            }}
            keepMounted
            transformOrigin={{
              vertical: 'top',
              horizontal: 'right',
            }}
            open={Boolean(anchorEl)}
            onClose={handleClose}
          >
            <NavLink to="/admin">
              <MenuItem onClick={handleClose}>Admin UI</MenuItem>
            </NavLink>
          </Menu>
        </Toolbar>
      </AppBar>

      {/* Routes */}
      <Routes>
        <Route path="/" element={<HomeUI />} />
        <Route path="/reader" element={<ReaderUI />} />
        <Route path="/admin" element={<AdminUI />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
