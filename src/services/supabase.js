/**
 * Holos Mobile — Supabase Client
 * Used for direct database access where needed (e.g., real-time subscriptions).
 * For most API calls, prefer using the api.js service which goes through the backend.
 */
import 'react-native-get-random-values';
import { createClient } from '@supabase/supabase-js';
import { SUPABASE_URL, SUPABASE_ANON_KEY } from '../config/env';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
