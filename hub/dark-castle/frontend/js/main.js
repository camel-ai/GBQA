/**
 * Main frontend controller.
 * Connect the API and UI layers and drive the game flow.
 */

let gameStarted = false;
let isProcessing = false;
let autoPlayMode = false;
let autoPlayIndex = 0;

const WALKTHROUGH_COMMANDS = [
    { cmd: "look", delay: 1500, desc: "Survey the hall" },
    { cmd: "take matches", delay: 1000, desc: "Pick up the matches [1/6]" },
    { cmd: "go north", delay: 1500, desc: "Move into the corridor" },
    { cmd: "go west", delay: 1500, desc: "Enter the bedroom" },
    { cmd: "open nightstand", delay: 1500, desc: "Open the nightstand drawer" },
    { cmd: "take small key", delay: 1000, desc: "Take the small key [2/6]" },
    { cmd: "read diary", delay: 2000, desc: "Read the diary for clues" },

    { cmd: "go east", delay: 1500, desc: "Return to the corridor" },
    { cmd: "go south", delay: 1500, desc: "Return to the hall" },
    { cmd: "use small key on storage room", delay: 1500, desc: "Unlock the storage room" },
    { cmd: "go east", delay: 1500, desc: "Enter the storage room" },
    { cmd: "take oil lamp", delay: 1000, desc: "Take the oil lamp [3/6]" },
    { cmd: "open toolbox", delay: 1500, desc: "Open the toolbox" },
    { cmd: "take key fragment b", delay: 1000, desc: "Claim key fragment B [4/6]" },

    { cmd: "go west", delay: 1500, desc: "Return to the hall" },
    { cmd: "go west", delay: 1500, desc: "Enter the kitchen" },
    { cmd: "take ladder", delay: 1000, desc: "Take the ladder [5/6]" },
    { cmd: "go east", delay: 1500, desc: "Return to the hall" },
    { cmd: "go north", delay: 1500, desc: "Move into the corridor" },
    { cmd: "go east", delay: 1500, desc: "Enter the library" },
    { cmd: "read scroll", delay: 2000, desc: "Read the scroll and learn the code" },
    { cmd: "use ladder", delay: 1500, desc: "Set up the ladder [4/6]" },
    { cmd: "go up", delay: 1500, desc: "Climb into the attic" },
    { cmd: "enter 3", delay: 2000, desc: "Enter the chest code '3'" },
    { cmd: "take key fragment a", delay: 1000, desc: "Claim key fragment A [5/6]" },

    { cmd: "go down", delay: 1500, desc: "Return to the library" },
    { cmd: "go west", delay: 1500, desc: "Return to the corridor" },
    { cmd: "go south", delay: 1500, desc: "Return to the hall" },
    { cmd: "drop small key", delay: 1000, desc: "Drop the spent small key [4/6]" },
    { cmd: "light oil lamp", delay: 1500, desc: "Light the oil lamp" },
    { cmd: "go down", delay: 1500, desc: "Descend into the basement" },
    { cmd: "oil iron door", delay: 2000, desc: "Oil the rusted iron door" },
    { cmd: "open iron door", delay: 1500, desc: "Open the iron door" },
    { cmd: "take key fragment c", delay: 1000, desc: "Claim key fragment C [5/6]" },

    { cmd: "combine", delay: 2500, desc: "Assemble the Key of Awakening" },
    { cmd: "go up", delay: 1500, desc: "Return to the hall" },
    { cmd: "use key of awakening", delay: 2000, desc: "Break the seal on the door" },
    { cmd: "open sealed door", delay: 3000, desc: "Escape the castle" },
];

const DEV_COMMAND = "devmode";
const AUTOPLAY_COMMAND = "autoplay";

async function startGame() {
    console.log("Starting a new game...");
    if (isProcessing) return;
    isProcessing = true;

    GameUI.showLoading();
    GameUI.clearOutput();

    try {
        const result = await GameAPI.newGame();
        console.log("API response:", result);

        if (result.success) {
            gameStarted = true;
            GameUI.addPureMessage(result.message, "success");

            if (result.state) {
                GameUI.updateState(result.state);
            }

            GameUI.enableInput();
        } else {
            GameUI.addPureMessage(`Error: ${result.message}`, "error");
        }
    } catch (error) {
        console.error("Game initialization error:", error);
        GameUI.addPureMessage(`Error: ${error.message}`, "error");
    }

    isProcessing = false;
}

window.startGame = startGame;

(function bootstrap() {
    "use strict";

    function init() {
        console.log("Initializing the game UI...");
        GameUI.init();
        bindEvents();
        checkServerHealth();
        console.log("Dark Castle: Night of Awakening loaded.");
    }

    function bindEvents() {
        const newGameBtn = document.getElementById("new-game-btn");
        if (newGameBtn) {
            newGameBtn.addEventListener("click", startGame);
        }

        const sendBtn = document.getElementById("send-btn");
        if (sendBtn) {
            sendBtn.addEventListener("click", () => GameUI.submitCommand());
        }

        window.onGameCommand = handleCommand;

        const exitsGrid = document.getElementById("exits-grid");
        if (exitsGrid) {
            exitsGrid.querySelectorAll(".exit-btn").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const direction = btn.dataset.direction;
                    if (direction === "look") {
                        handleCommand("look");
                    } else if (!btn.disabled) {
                        handleCommand(`go ${direction}`);
                    }
                });
            });
        }

        document.querySelectorAll(".quick-btn").forEach((btn) => {
            btn.addEventListener("click", () => {
                handleCommand(btn.dataset.command);
            });
        });
    }

    async function checkServerHealth() {
        try {
            const result = await GameAPI.healthCheck();
            console.log("Server status:", result);

            if (!result.status) {
                GameUI.addPureMessage(
                    "Unable to connect to the game server. Make sure the backend is running.",
                    "error",
                );
            }
        } catch (error) {
            console.error("Server health check failed:", error);
        }
    }

    async function handleCommand(command) {
        if (!gameStarted || isProcessing) return;
        if (!command || !command.trim()) return;

        const normalized = command.trim().toLowerCase();

        if (normalized === DEV_COMMAND || normalized === AUTOPLAY_COMMAND) {
            showAutoPlayConfirm();
            return;
        }

        if (normalized === "stop" && autoPlayMode) {
            stopAutoPlay();
            return;
        }

        isProcessing = true;
        GameUI.showLoading();

        try {
            const result = await GameAPI.sendCommand(command);
            GameUI.addMessage(command, result.message, !result.success, result.game_over);

            if (result.state) {
                GameUI.updateState(result.state);
            }

            if (result.game_over) {
                gameStarted = false;
                autoPlayMode = false;
                GameUI.showGameOver();
                celebrateVictory();
            } else {
                GameUI.enableInput();
            }
        } catch (error) {
            console.error("Command handling failed:", error);
            GameUI.addPureMessage(`Error: ${error.message}`, "error");
            GameUI.enableInput();
        }

        isProcessing = false;
    }

    function showAutoPlayConfirm() {
        const overlay = document.createElement("div");
        overlay.id = "dev-overlay";
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        `;

        const dialog = document.createElement("div");
        dialog.style.cssText = `
            background: linear-gradient(135deg, #1a1a24, #12121a);
            border: 2px solid #7b4dff;
            border-radius: 12px;
            padding: 30px 40px;
            text-align: center;
            max-width: 500px;
            box-shadow: 0 0 40px rgba(123, 77, 255, 0.5);
        `;

        dialog.innerHTML = `
            <h2 style="color: #c9a227; font-family: 'Cinzel', serif; margin-bottom: 15px;">
                Developer Mode
            </h2>
            <p style="color: #e8e4dc; margin-bottom: 10px; line-height: 1.6;">
                Start the full autoplay castle escape demonstration.
            </p>
            <p style="color: #9a968e; font-size: 0.9rem; margin-bottom: 25px;">
                The game will reset and run the complete winning route automatically.<br>
                ${WALKTHROUGH_COMMANDS.length} total steps, about 2 minutes to complete.<br>
                <span style="color: #00d4aa;">Type 'stop' at any time to interrupt the run.</span>
            </p>
            <div style="display: flex; gap: 15px; justify-content: center;">
                <button id="confirm-autoplay" style="
                    padding: 12px 30px;
                    background: linear-gradient(135deg, #7b4dff, #5a3acc);
                    border: none;
                    border-radius: 6px;
                    color: white;
                    font-size: 1rem;
                    cursor: pointer;
                    transition: transform 0.2s;
                ">Start Demo</button>
                <button id="cancel-autoplay" style="
                    padding: 12px 30px;
                    background: #2a2a36;
                    border: 1px solid #5a574f;
                    border-radius: 6px;
                    color: #9a968e;
                    font-size: 1rem;
                    cursor: pointer;
                    transition: transform 0.2s;
                ">Cancel</button>
            </div>
        `;

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        document.getElementById("confirm-autoplay").addEventListener("click", () => {
            document.body.removeChild(overlay);
            startAutoPlay();
        });

        document.getElementById("cancel-autoplay").addEventListener("click", () => {
            document.body.removeChild(overlay);
            GameUI.addPureMessage("Autoplay was cancelled.", "");
        });
    }

    async function startAutoPlay() {
        console.log("Starting autoplay demonstration...");

        GameUI.clearOutput();
        GameUI.addPureMessage(
            `
===============================================================
                    Developer Mode: Autoplay
===============================================================
Resetting the game and beginning the guided escape route...
Type 'stop' at any time to interrupt the run.
===============================================================
            `,
            "success",
        );

        const result = await GameAPI.newGame();
        if (!result.success) {
            GameUI.addPureMessage(`Reset failed: ${result.message}`, "error");
            return;
        }

        gameStarted = true;
        autoPlayMode = true;
        autoPlayIndex = 0;

        GameUI.addPureMessage(result.message, "success");
        if (result.state) {
            GameUI.updateState(result.state);
        }

        showAutoPlayIndicator();
        setTimeout(() => executeNextAutoCommand(), 2000);
    }

    function showAutoPlayIndicator() {
        let indicator = document.getElementById("autoplay-indicator");
        if (!indicator) {
            indicator = document.createElement("div");
            indicator.id = "autoplay-indicator";
            indicator.style.cssText = `
                position: fixed;
                top: 80px;
                right: 20px;
                background: linear-gradient(135deg, rgba(123, 77, 255, 0.9), rgba(90, 58, 204, 0.9));
                border: 1px solid #7b4dff;
                border-radius: 8px;
                padding: 10px 15px;
                z-index: 200;
                font-size: 0.85rem;
                box-shadow: 0 4px 20px rgba(123, 77, 255, 0.4);
            `;
            document.body.appendChild(indicator);
        }

        updateAutoPlayIndicator();
    }

    function updateAutoPlayIndicator() {
        const indicator = document.getElementById("autoplay-indicator");
        if (indicator && autoPlayMode) {
            const current = WALKTHROUGH_COMMANDS[autoPlayIndex];
            const progress = Math.round((autoPlayIndex / WALKTHROUGH_COMMANDS.length) * 100);
            indicator.innerHTML = `
                <div style="color: #c9a227; font-weight: bold; margin-bottom: 5px;">
                    Autoplay Running
                </div>
                <div style="color: white; margin-bottom: 5px;">
                    Step ${autoPlayIndex + 1}/${WALKTHROUGH_COMMANDS.length}
                </div>
                <div style="background: #2a2a36; border-radius: 4px; height: 6px; margin-bottom: 5px;">
                    <div style="background: #c9a227; height: 100%; width: ${progress}%; border-radius: 4px; transition: width 0.3s;"></div>
                </div>
                <div style="color: #9a968e; font-size: 0.8rem;">
                    ${current ? current.desc : "Complete"}
                </div>
            `;
        }
    }

    async function executeNextAutoCommand() {
        if (!autoPlayMode || autoPlayIndex >= WALKTHROUGH_COMMANDS.length) {
            stopAutoPlay();
            return;
        }

        const step = WALKTHROUGH_COMMANDS[autoPlayIndex];
        updateAutoPlayIndicator();
        GameUI.addPureMessage(`\nStep ${autoPlayIndex + 1}: ${step.desc}`, "");

        isProcessing = true;

        try {
            const result = await GameAPI.sendCommand(step.cmd);
            GameUI.addMessage(step.cmd, result.message, !result.success, result.game_over);

            if (result.state) {
                GameUI.updateState(result.state);
            }

            if (result.game_over) {
                gameStarted = false;
                autoPlayMode = false;
                isProcessing = false;
                removeAutoPlayIndicator();
                GameUI.showGameOver();
                celebrateVictory();
                GameUI.addPureMessage("\nAutoplay demonstration complete.", "success");
                return;
            }

            autoPlayIndex += 1;
            setTimeout(() => executeNextAutoCommand(), step.delay);
        } catch (error) {
            console.error("Autoplay failed:", error);
            GameUI.addPureMessage(`Autoplay error: ${error.message}`, "error");
            stopAutoPlay();
        }

        isProcessing = false;
    }

    function stopAutoPlay() {
        autoPlayMode = false;
        autoPlayIndex = 0;
        removeAutoPlayIndicator();
        GameUI.addPureMessage("\nAutoplay stopped. You can continue playing manually.", "");
        GameUI.enableInput();
    }

    function removeAutoPlayIndicator() {
        const indicator = document.getElementById("autoplay-indicator");
        if (indicator) {
            indicator.remove();
        }
    }

    function celebrateVictory() {
        const lightning = GameUI.elements.lightning;
        let flashCount = 0;

        const flashInterval = setInterval(() => {
            lightning.classList.add("flash");
            setTimeout(() => lightning.classList.remove("flash"), 100);

            flashCount += 1;
            if (flashCount > 5) {
                clearInterval(flashInterval);
            }
        }, 300);

        const particles = GameUI.elements.particles;
        for (let i = 0; i < 50; i += 1) {
            const particle = document.createElement("div");
            particle.className = "particle";
            particle.style.left = `${Math.random() * 100}%`;
            particle.style.background = "#c9a227";
            particle.style.animationDelay = `${Math.random() * 2}s`;
            particle.style.animationDuration = "3s";
            particles.appendChild(particle);
            setTimeout(() => particle.remove(), 3000);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
