/**
 * Holos Mobile — API Service
 * All backend communication goes through here.
 */
import { API_BASE_URL } from '../config/env';

/**
 * Scan a room image and get identified items.
 * @param {string} imageUri - Local URI of the captured/selected image
 * @param {string} homeName - Name of the home location
 * @param {string} roomName - Name of the room
 * @returns {Promise<Object>} Scan results with items array
 */
export const scanRoom = async (imageUri, homeName = 'My House', roomName = 'Living Room') => {
    try {
        const formData = new FormData();

        const filename = imageUri.split('/').pop();
        const match = /\.(\w+)$/.exec(filename);
        const type = match ? `image/${match[1]}` : `image`;

        formData.append('image', { uri: imageUri, name: filename, type });
        formData.append('home_name', homeName);
        formData.append('room_name', roomName);

        const response = await fetch(`${API_BASE_URL}/api/scan`, {
            method: 'POST',
            body: formData,
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });

        const result = await response.json();
        return result;
    } catch (error) {
        console.error('API Scan Error:', error);
        throw error;
    }
};

/**
 * Save an identified item to the user's inventory.
 * @param {Object} itemData - The item object from scan results
 * @param {string} token - Auth token from login
 * @returns {Promise<Object>} Saved item with DB id
 */
export const saveItem = async (itemData, token) => {
    try {
        const response = await fetch(`${API_BASE_URL}/api/items/save`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify(itemData),
        });
        return await response.json();
    } catch (error) {
        console.error('API Save Error:', error);
        throw error;
    }
};

/**
 * Fetch all items for the current user.
 * @param {string} token - Auth token
 * @param {Object} options - Query options
 * @param {string} options.query - Search query
 * @param {boolean} options.archived - Show archived items
 * @returns {Promise<Object>} Items array
 */
export const fetchItems = async (token, { query = '', archived = false } = {}) => {
    try {
        const params = new URLSearchParams({
            q: query,
            archived: archived.toString(),
        });
        const response = await fetch(`${API_BASE_URL}/api/items?${params}`, {
            headers: {
                'Authorization': `Bearer ${token}`,
            },
        });
        return await response.json();
    } catch (error) {
        console.error('API Fetch Error:', error);
        throw error;
    }
};

/**
 * Login with email and password.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<Object>} Session and user data
 */
export const login = async (email, password) => {
    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });
        return await response.json();
    } catch (error) {
        console.error('API Login Error:', error);
        throw error;
    }
};

/**
 * Register a new account.
 * @param {string} email
 * @param {string} password
 * @param {string} fullName
 * @returns {Promise<Object>}
 */
export const register = async (email, password, fullName = '') => {
    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, full_name: fullName }),
        });
        return await response.json();
    } catch (error) {
        console.error('API Register Error:', error);
        throw error;
    }
};

/**
 * Archive an item.
 * @param {string} itemId
 * @param {string} token
 */
export const archiveItem = async (itemId, token) => {
    try {
        const response = await fetch(`${API_BASE_URL}/api/items/${itemId}/archive`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
        });
        return await response.json();
    } catch (error) {
        console.error('API Archive Error:', error);
        throw error;
    }
};

/**
 * Generate an AI resale listing for an item.
 * @param {string} itemId
 * @param {string} token
 */
export const getResaleListing = async (itemId, token) => {
    try {
        const response = await fetch(`${API_BASE_URL}/api/items/${itemId}/resale`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        return await response.json();
    } catch (error) {
        console.error('API Resale Error:', error);
        throw error;
    }
};

/**
 * Get the estate value report.
 * @param {string} token
 */
export const getEstateReport = async (token) => {
    try {
        const response = await fetch(`${API_BASE_URL}/api/reports/estate`, {
            headers: { 'Authorization': `Bearer ${token}` },
        });
        return await response.json();
    } catch (error) {
        console.error('API Report Error:', error);
        throw error;
    }
};

/**
 * Check backend health status.
 */
export const checkHealth = async () => {
    try {
        const response = await fetch(`${API_BASE_URL}/api/health`);
        return await response.json();
    } catch (error) {
        return { status: 'unreachable', error: error.message };
    }
};
