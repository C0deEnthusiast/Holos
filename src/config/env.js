/**
 * Holos Mobile — Environment Configuration
 * 
 * Change BACKEND_IP to match your development machine's local IP.
 * Find it by running `ipconfig` (Windows) or `ifconfig` (Mac/Linux).
 *
 * For production, set USE_PRODUCTION to true and update PRODUCTION_URL.
 */

const USE_PRODUCTION = false;

// Development — your local machine's IP on the same Wi-Fi
const DEV_BACKEND_IP = '10.0.0.223';
const DEV_BACKEND_PORT = '5000';

// Production — your deployed backend URL (e.g., Railway, Render, Cloud Run)
const PRODUCTION_URL = 'https://holos-api.example.com';

export const API_BASE_URL = USE_PRODUCTION
    ? PRODUCTION_URL
    : `http://${DEV_BACKEND_IP}:${DEV_BACKEND_PORT}`;

export const SUPABASE_URL = 'https://wsebkbzjqgftbdepfxlj.supabase.co';
export const SUPABASE_ANON_KEY = 'sb_publishable_6Mm0cMpMglCivGkavLIozw_aNrQI9LB';
