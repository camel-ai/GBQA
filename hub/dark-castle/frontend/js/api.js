/**
 * API communication layer.
 * Handle all requests to the backend server.
 */

const API = {
    baseURL: "/api",
    gameId: null,

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const defaultOptions = {
            headers: {
                "Content-Type": "application/json",
            },
            credentials: "include",
        };

        const mergedOptions = { ...defaultOptions, ...options };

        try {
            const response = await fetch(url, mergedOptions);
            return await response.json();
        } catch (error) {
            console.error("API request failed:", error);
            return {
                success: false,
                message: "Network error. Unable to reach the server. Make sure the backend is running.",
                error: error.message,
            };
        }
    },

    async newGame() {
        const data = await this.request("/agent/new", {
            method: "POST",
        });

        if (data.success && data.game_id) {
            this.gameId = data.game_id;
        }

        return data;
    },

    async sendCommand(command) {
        if (!this.gameId) {
            return {
                success: false,
                message: "The game has not started yet. Start a new game first.",
            };
        }

        return await this.request("/agent/command", {
            method: "POST",
            body: JSON.stringify({
                game_id: this.gameId,
                command,
            }),
        });
    },

    async getState() {
        if (!this.gameId) {
            return {
                success: false,
                message: "The game has not started yet.",
            };
        }

        return await this.request(`/agent/state/${this.gameId}`, {
            method: "GET",
        });
    },

    async resetGame() {
        return await this.newGame();
    },

    async healthCheck() {
        return await this.request("/health", {
            method: "GET",
        });
    },
};

window.GameAPI = API;
