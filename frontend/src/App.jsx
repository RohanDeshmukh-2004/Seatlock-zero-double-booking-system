import React, { useState, useEffect, useRef } from 'react';
import { apiRequest, getAuthToken, setAuthToken, getCurrentUser, setCurrentUser } from './api';
import { Film, Ticket, Clock, ShieldCheck, AlertCircle, LogOut, User, RefreshCw, CheckCircle2, ChevronRight, Lock } from 'lucide-react';

export default function App() {
  const [currentUser, setUser] = useState(getCurrentUser());
  const [activeTab, setActiveTab] = useState('movies'); // 'movies', 'seatmap', 'bookings', 'login'
  const [authMode, setAuthMode] = useState('login'); // 'login' or 'register'
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authError, setAuthError] = useState('');

  // Movie & Show selection
  const [movies, setMovies] = useState([]);
  const [shows, setShows] = useState([]);
  const [selectedMovie, setSelectedMovie] = useState(null);
  const [selectedShow, setSelectedShow] = useState(null);

  // Seat selection & locking
  const [seats, setSeats] = useState([]);
  const [selectedSeatLabels, setSelectedSeatLabels] = useState([]);
  const [heldSeats, setHeldSeats] = useState([]); // seats locked by me
  const [lockExpiresAt, setLockExpiresAt] = useState(null);
  const [timeLeft, setTimeLeft] = useState(0);
  const [feedback, setFeedback] = useState(null); // { type: 'success' | 'error', msg: '' }

  // My bookings
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(false);

  // Load initial movies
  useEffect(() => {
    fetchMovies();
  }, []);

  // Countdown timer for locks
  useEffect(() => {
    if (!lockExpiresAt) {
      setTimeLeft(0);
      return;
    }

    const interval = setInterval(() => {
      const remaining = Math.max(0, Math.floor((new Date(lockExpiresAt).getTime() - Date.now()) / 1000));
      setTimeLeft(remaining);

      if (remaining <= 0) {
        setLockExpiresAt(null);
        setHeldSeats([]);
        setSelectedSeatLabels([]);
        setFeedback({ type: 'error', msg: 'Seat lock expired! Seats have been automatically released.' });
        clearInterval(interval);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [lockExpiresAt]);

  // Live seat polling every 3 seconds when in 'seatmap'
  useEffect(() => {
    if (activeTab !== 'seatmap' || !selectedShow) return;

    fetchSeats(selectedShow.id);
    const poller = setInterval(() => {
      fetchSeats(selectedShow.id, true);
    }, 3000);

    return () => clearInterval(poller);
  }, [activeTab, selectedShow]);

  async function fetchMovies() {
    try {
      const data = await apiRequest('/movies');
      setMovies(data);
      if (data.length > 0 && !selectedMovie) {
        selectMovie(data[0]);
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function selectMovie(movie) {
    setSelectedMovie(movie);
    try {
      const data = await apiRequest(`/shows?movie_id=${movie.id}`);
      setShows(data);
      if (data.length > 0) {
        setSelectedShow(data[0]);
      } else {
        setSelectedShow(null);
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function fetchSeats(showId, isSilent = false) {
    if (!isSilent) setLoading(true);
    try {
      const data = await apiRequest(`/shows/${showId}/seats`);
      setSeats(data);
    } catch (err) {
      console.error(err);
    } finally {
      if (!isSilent) setLoading(false);
    }
  }

  async function fetchBookings() {
    if (!currentUser) return;
    try {
      const data = await apiRequest('/bookings/me');
      setBookings(data);
    } catch (err) {
      console.error(err);
    }
  }

  // Auth handlers
  async function handleAuth(e) {
    e.preventDefault();
    setAuthError('');
    try {
      const endpoint = authMode === 'login' ? '/auth/login' : '/auth/register';
      const res = await apiRequest(endpoint, {
        method: 'POST',
        body: JSON.stringify({ email: authEmail, password: authPassword })
      });
      setAuthToken(res.access_token);
      setCurrentUser(res.user);
      setUser(res.user);
      setAuthEmail('');
      setAuthPassword('');
      setActiveTab('movies');
      setFeedback({ type: 'success', msg: `Welcome back, ${res.user.email}!` });
    } catch (err) {
      setAuthError(err.message || 'Authentication failed');
    }
  }

  function handleLogout() {
    setAuthToken(null);
    setCurrentUser(null);
    setUser(null);
    setHeldSeats([]);
    setLockExpiresAt(null);
    setSelectedSeatLabels([]);
    setActiveTab('movies');
  }

  // Seat interaction
  function toggleSeat(seat) {
    if (seat.status !== 'AVAILABLE' && !heldSeats.includes(seat.seat_label)) {
      return; // Cannot select booked or other's locked seat
    }

    if (heldSeats.length > 0) {
      setFeedback({ type: 'error', msg: 'You currently have active locks. Confirm or unlock them first.' });
      return;
    }

    setSelectedSeatLabels(prev =>
      prev.includes(seat.seat_label)
        ? prev.filter(label => label !== seat.seat_label)
        : [...prev, seat.seat_label]
    );
  }

  async function handleLockSeats() {
    if (!currentUser) {
      setActiveTab('login');
      setFeedback({ type: 'error', msg: 'Please login or register to lock seats.' });
      return;
    }
    if (selectedSeatLabels.length === 0) return;

    try {
      setFeedback(null);
      const res = await apiRequest(`/shows/${selectedShow.id}/lock`, {
        method: 'POST',
        body: JSON.stringify({ seats: selectedSeatLabels })
      });

      setHeldSeats(res.seats);
      setLockExpiresAt(res.locked_until);
      setFeedback({ type: 'success', msg: `Locked seats: ${res.seats.join(', ')} for 5 minutes!` });
      fetchSeats(selectedShow.id, true);
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Seat lock conflict' });
      fetchSeats(selectedShow.id, true);
    }
  }

  async function handleUnlockSeats() {
    if (heldSeats.length === 0) return;
    try {
      await apiRequest(`/shows/${selectedShow.id}/unlock`, {
        method: 'POST',
        body: JSON.stringify({ seats: heldSeats })
      });
      setHeldSeats([]);
      setLockExpiresAt(null);
      setSelectedSeatLabels([]);
      setFeedback({ type: 'success', msg: 'Seats released successfully.' });
      fetchSeats(selectedShow.id, true);
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Failed to unlock seats' });
    }
  }

  async function handleConfirmBooking() {
    if (heldSeats.length === 0) return;
    try {
      const res = await apiRequest('/bookings/confirm', {
        method: 'POST',
        body: JSON.stringify({
          show_id: selectedShow.id,
          seats: heldSeats,
          payment_token: 'pay_token_success'
        })
      });

      setHeldSeats([]);
      setLockExpiresAt(null);
      setSelectedSeatLabels([]);
      setFeedback({
        type: 'success',
        msg: `Booking confirmed! Reference: ${res.booking_reference}`
      });
      fetchSeats(selectedShow.id, true);
      fetchBookings();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Booking confirmation failed' });
      fetchSeats(selectedShow.id, true);
    }
  }

  async function handleCancelBooking(bookingId) {
    try {
      await apiRequest(`/bookings/${bookingId}/cancel`, { method: 'POST' });
      setFeedback({ type: 'success', msg: 'Booking cancelled. Seat is now available for others!' });
      fetchBookings();
      if (selectedShow) fetchSeats(selectedShow.id, true);
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Failed to cancel booking' });
    }
  }

  // Format countdown mm:ss
  const formatTime = (secs) => {
    const m = Math.floor(secs / 60).toString().padStart(2, '0');
    const s = (secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3 cursor-pointer" onClick={() => setActiveTab('movies')}>
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Film className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="text-xl font-bold tracking-tight text-white">Seat<span className="text-indigo-400">Lock</span></span>
              <span className="hidden sm:inline-block ml-2 px-2 py-0.5 text-xs bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-full font-mono">Row-Lock Concurrency</span>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={() => setActiveTab('movies')}
              className={`px-3 py-1.5 text-sm font-medium rounded-lg transition ${activeTab === 'movies' ? 'bg-indigo-600 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-800'}`}
            >
              Movies
            </button>

            {currentUser && (
              <button
                onClick={() => { setActiveTab('bookings'); fetchBookings(); }}
                className={`px-3 py-1.5 text-sm font-medium rounded-lg transition ${activeTab === 'bookings' ? 'bg-indigo-600 text-white' : 'text-slate-300 hover:text-white hover:bg-slate-800'}`}
              >
                My Bookings
              </button>
            )}

            {currentUser ? (
              <div className="flex items-center space-x-2 pl-2 border-l border-slate-800">
                <span className="text-xs text-slate-400 hidden md:inline font-mono">{currentUser.email}</span>
                <button
                  onClick={handleLogout}
                  className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition"
                  title="Logout"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setActiveTab('login')}
                className="px-4 py-1.5 text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition shadow-sm"
              >
                Sign In
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Global Toast / Feedback */}
      {feedback && (
        <div className={`py-2.5 px-4 text-center text-sm font-medium transition flex items-center justify-center space-x-2 ${
          feedback.type === 'success' ? 'bg-emerald-950/80 text-emerald-300 border-b border-emerald-800' : 'bg-rose-950/80 text-rose-300 border-b border-rose-800'
        }`}>
          {feedback.type === 'success' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          <span>{feedback.msg}</span>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8">
        {/* VIEW 1: MOVIES LIST */}
        {activeTab === 'movies' && (
          <div>
            <div className="mb-8">
              <h1 className="text-3xl font-extrabold text-white tracking-tight">Now Showing</h1>
              <p className="text-slate-400 text-sm mt-1">Select a movie and screening showtime to enter the live seat map.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {movies.map(movie => (
                <div
                  key={movie.id}
                  className={`group relative rounded-2xl overflow-hidden border transition-all duration-300 bg-slate-900/60 flex flex-col ${
                    selectedMovie?.id === movie.id ? 'border-indigo-500 ring-2 ring-indigo-500/20' : 'border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="aspect-[16/10] overflow-hidden bg-slate-800 relative">
                    <img
                      src={movie.poster_url || "https://images.unsplash.com/photo-1536440136628-849c177e76a1?w=800"}
                      alt={movie.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition duration-500"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/20 to-transparent"></div>
                    <div className="absolute bottom-3 left-3 flex items-center space-x-2">
                      <span className="px-2 py-0.5 text-xs bg-slate-900/90 text-slate-300 rounded font-medium border border-slate-700">
                        {movie.duration_minutes} mins
                      </span>
                    </div>
                  </div>

                  <div className="p-5 flex-1 flex flex-col justify-between">
                    <div>
                      <h2 className="text-xl font-bold text-white group-hover:text-indigo-400 transition">{movie.title}</h2>
                      <p className="text-slate-400 text-sm mt-2 line-clamp-3 leading-relaxed">{movie.description}</p>
                    </div>

                    <div className="mt-6 pt-4 border-t border-slate-800">
                      <button
                        onClick={() => {
                          selectMovie(movie);
                          setActiveTab('seatmap');
                        }}
                        className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-semibold flex items-center justify-center space-x-2 transition shadow-md shadow-indigo-600/20"
                      >
                        <span>Select Showtime & Seats</span>
                        <ChevronRight className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* VIEW 2: LIVE SEAT MAP (PHASE 6 & 7) */}
        {activeTab === 'seatmap' && selectedMovie && (
          <div>
            {/* Show selector header */}
            <div className="flex flex-col lg:flex-row lg:items-center justify-between pb-6 mb-6 border-b border-slate-800 gap-4">
              <div>
                <span className="text-xs uppercase tracking-wider text-indigo-400 font-semibold">{selectedMovie.title}</span>
                <h1 className="text-2xl font-bold text-white mt-0.5">Select Your Seats</h1>
              </div>

              {/* Showtimes picker */}
              <div className="flex items-center space-x-2 overflow-x-auto pb-2 lg:pb-0">
                {shows.map(show => (
                  <button
                    key={show.id}
                    onClick={() => {
                      setSelectedShow(show);
                      setSelectedSeatLabels([]);
                      setHeldSeats([]);
                      setLockExpiresAt(null);
                    }}
                    className={`px-3.5 py-2 rounded-xl text-xs font-semibold whitespace-nowrap transition border ${
                      selectedShow?.id === show.id
                        ? 'bg-indigo-600 border-indigo-500 text-white shadow-md shadow-indigo-500/20'
                        : 'bg-slate-900 border-slate-800 text-slate-300 hover:border-slate-700'
                    }`}
                  >
                    <div>{show.screen_name}</div>
                    <div className="text-[10px] opacity-75">{new Date(show.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • ₹{show.price}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* 5-minute countdown banner if lock active */}
            {lockExpiresAt && timeLeft > 0 && (
              <div className="mb-6 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-between animate-pulse">
                <div className="flex items-center space-x-3">
                  <div className="w-9 h-9 rounded-lg bg-amber-500/20 flex items-center justify-center text-amber-400">
                    <Clock className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-amber-300">Seats Locked For You</h4>
                    <p className="text-xs text-amber-200/70">Complete your payment before the timer expires to secure your tickets.</p>
                  </div>
                </div>
                <div className="text-right">
                  <span className="font-mono text-2xl font-black text-amber-400">{formatTime(timeLeft)}</span>
                </div>
              </div>
            )}

            {/* Seat Map Area */}
            <div className="bg-slate-900/60 rounded-2xl border border-slate-800 p-6 flex flex-col items-center">
              {/* Screen Indicator */}
              <div className="w-full max-w-xl mb-10 flex flex-col items-center">
                <div className="h-1.5 w-full bg-gradient-to-r from-transparent via-indigo-500 to-transparent rounded-full shadow-[0_0_15px_rgba(99,102,241,0.5)]"></div>
                <span className="text-[11px] uppercase tracking-widest text-slate-500 font-semibold mt-2">All Eyes This Way • Cinema Screen</span>
              </div>

              {/* Grid 10x10 seats */}
              <div className="grid grid-cols-10 gap-2 sm:gap-2.5 max-w-2xl w-full p-2">
                {seats.map(seat => {
                  const isSelected = selectedSeatLabels.includes(seat.seat_label);
                  const isHeldByMe = heldSeats.includes(seat.seat_label);
                  const isBooked = seat.status === 'BOOKED';
                  const isLockedByOther = seat.status === 'LOCKED' && !isHeldByMe;

                  let colorClass = 'bg-slate-800 text-slate-300 hover:bg-slate-700 hover:scale-105 cursor-pointer border-slate-700'; // Available
                  if (isSelected || isHeldByMe) {
                    colorClass = 'bg-emerald-500 text-slate-950 font-bold shadow-lg shadow-emerald-500/30 scale-105 border-emerald-400'; // Selected
                  } else if (isLockedByOther) {
                    colorClass = 'bg-amber-500/80 text-slate-950 font-bold border-amber-400 cursor-not-allowed opacity-90'; // Locked by someone else
                  } else if (isBooked) {
                    colorClass = 'bg-rose-900/40 text-rose-500/50 border-rose-900/40 cursor-not-allowed'; // Booked
                  }

                  return (
                    <button
                      key={seat.id}
                      onClick={() => toggleSeat(seat)}
                      disabled={isBooked || isLockedByOther}
                      className={`h-9 sm:h-10 rounded-lg text-xs font-mono flex items-center justify-center transition border ${colorClass}`}
                      title={`${seat.seat_label} - ${seat.status}`}
                    >
                      {seat.seat_label}
                    </button>
                  );
                })}
              </div>

              {/* Legend */}
              <div className="flex flex-wrap items-center justify-center gap-6 mt-8 pt-6 border-t border-slate-800/80 text-xs text-slate-400">
                <div className="flex items-center space-x-2">
                  <div className="w-4 h-4 rounded bg-slate-800 border border-slate-700"></div>
                  <span>Available</span>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="w-4 h-4 rounded bg-emerald-500 border border-emerald-400"></div>
                  <span>Selected (You)</span>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="w-4 h-4 rounded bg-amber-500 border border-amber-400"></div>
                  <span>Locked (In Checkout)</span>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="w-4 h-4 rounded bg-rose-900/40 border border-rose-900/40"></div>
                  <span>Booked</span>
                </div>
                <div className="flex items-center space-x-1.5 text-indigo-400">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Polling every 3s</span>
                </div>
              </div>
            </div>

            {/* Bottom Floating Bar */}
            {(selectedSeatLabels.length > 0 || heldSeats.length > 0) && (
              <div className="fixed bottom-6 left-1/2 -translate-x-1/2 w-[92%] max-w-xl bg-slate-900/95 border border-slate-700 backdrop-blur-lg rounded-2xl p-4 shadow-2xl flex items-center justify-between z-40">
                <div>
                  <span className="text-xs text-slate-400">Selected Seats:</span>
                  <div className="text-sm font-bold text-white flex items-center space-x-1">
                    <span>{(heldSeats.length > 0 ? heldSeats : selectedSeatLabels).join(', ')}</span>
                    <span className="text-slate-500">•</span>
                    <span className="text-emerald-400">₹{((heldSeats.length > 0 ? heldSeats.length : selectedSeatLabels.length) * (selectedShow?.price || 0)).toFixed(2)}</span>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  {heldSeats.length > 0 ? (
                    <>
                      <button
                        onClick={handleUnlockSeats}
                        className="px-3.5 py-2 text-xs font-semibold text-rose-400 hover:bg-rose-500/10 rounded-xl transition border border-rose-500/30"
                      >
                        Release Lock
                      </button>
                      <button
                        onClick={handleConfirmBooking}
                        className="px-5 py-2 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl transition shadow-lg shadow-emerald-600/30 flex items-center space-x-1.5"
                      >
                        <ShieldCheck className="w-4 h-4" />
                        <span>Confirm & Pay</span>
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={handleLockSeats}
                      className="px-6 py-2.5 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl transition shadow-lg shadow-indigo-600/30 flex items-center space-x-1.5"
                    >
                      <Lock className="w-3.5 h-3.5" />
                      <span>Lock Seats (5m)</span>
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* VIEW 3: MY BOOKINGS (PHASE 5/7) */}
        {activeTab === 'bookings' && (
          <div>
            <div className="mb-8">
              <h1 className="text-3xl font-extrabold text-white tracking-tight">My Bookings</h1>
              <p className="text-slate-400 text-sm mt-1">Confirmed tickets and reservations tied to your account.</p>
            </div>

            {bookings.length === 0 ? (
              <div className="text-center py-16 bg-slate-900/40 rounded-2xl border border-slate-800">
                <Ticket className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                <h3 className="text-lg font-bold text-slate-300">No bookings yet</h3>
                <p className="text-slate-500 text-sm mt-1 mb-4">Pick a show and book your first seat.</p>
                <button
                  onClick={() => setActiveTab('movies')}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-xl text-xs font-semibold"
                >
                  Browse Movies
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                {bookings.map(b => (
                  <div
                    key={b.id}
                    className="p-5 rounded-2xl bg-slate-900/60 border border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                  >
                    <div>
                      <div className="flex items-center space-x-2">
                        <span className="font-mono text-xs text-indigo-400 font-bold">{b.booking_reference}</span>
                        <span className={`px-2 py-0.5 text-[10px] rounded-full font-bold uppercase ${
                          b.status === 'CONFIRMED' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400'
                        }`}>
                          {b.status}
                        </span>
                      </div>
                      <h3 className="text-lg font-bold text-white mt-1">{b.movie_title}</h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {b.screen_name} • Seat <strong className="text-slate-200">{b.seat_label}</strong> • ₹{b.price}
                      </p>
                    </div>

                    {b.status === 'CONFIRMED' && (
                      <button
                        onClick={() => handleCancelBooking(b.id)}
                        className="px-4 py-2 text-xs font-semibold text-rose-400 hover:bg-rose-500/10 rounded-xl transition border border-rose-500/20 self-start sm:self-auto"
                      >
                        Cancel Booking
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* VIEW 4: LOGIN / REGISTER */}
        {activeTab === 'login' && (
          <div className="max-w-md mx-auto py-12">
            <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur">
              <div className="text-center mb-6">
                <div className="w-12 h-12 rounded-xl bg-indigo-600/20 text-indigo-400 flex items-center justify-center mx-auto mb-3 border border-indigo-500/30">
                  <User className="w-6 h-6" />
                </div>
                <h2 className="text-2xl font-bold text-white">{authMode === 'login' ? 'Sign In to SeatLock' : 'Create an Account'}</h2>
                <p className="text-xs text-slate-400 mt-1">Book seats with sub-second concurrency guarantees.</p>
              </div>

              {authError && (
                <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center space-x-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{authError}</span>
                </div>
              )}

              <form onSubmit={handleAuth} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Email</label>
                  <input
                    type="email"
                    required
                    value={authEmail}
                    onChange={e => setAuthEmail(e.target.value)}
                    placeholder="user@seatlock.com"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-indigo-500 transition"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={authPassword}
                    onChange={e => setAuthPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-indigo-500 transition"
                  />
                </div>

                <button
                  type="submit"
                  className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl text-sm transition shadow-lg shadow-indigo-600/20 mt-2"
                >
                  {authMode === 'login' ? 'Sign In' : 'Register'}
                </button>
              </form>

              <div className="mt-6 text-center text-xs text-slate-400">
                {authMode === 'login' ? "Don't have an account? " : "Already have an account? "}
                <button
                  onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(''); }}
                  className="text-indigo-400 hover:underline font-semibold"
                >
                  {authMode === 'login' ? 'Register now' : 'Sign In'}
                </button>
              </div>

              {authMode === 'login' && (
                <div className="mt-6 pt-4 border-t border-slate-800 text-center text-xs text-slate-500">
                  <span className="font-semibold text-slate-400">Test Account:</span> user@seatlock.com / user123
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
