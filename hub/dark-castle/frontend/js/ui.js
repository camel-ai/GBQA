/**
 * UI rendering module.
 * Own DOM updates and visual effects for the game shell.
 */

const UI = {
    elements: {},
    commandHistory: [],
    historyIndex: -1,

    init() {
        this.elements = {
            gameOutput: document.getElementById("game-output"),
            commandInput: document.getElementById("command-input"),
            sendBtn: document.getElementById("send-btn"),
            newGameBtn: document.getElementById("new-game-btn"),
            currentRoom: document.getElementById("current-room"),
            inventoryCount: document.getElementById("inventory-count"),
            turnCount: document.getElementById("turn-count"),
            inventoryList: document.getElementById("inventory-list"),
            exitsGrid: document.getElementById("exits-grid"),
            lightStatus: document.getElementById("light-status"),
            lightText: document.getElementById("light-text"),
            keyFragments: document.getElementById("key-fragments"),
            particles: document.getElementById("particles"),
            lightning: document.getElementById("lightning"),
        };

        this.initParticles();
        this.initLightning();
        this.bindKeyboardEvents();
    },

    initParticles() {
        const container = this.elements.particles;
        const particleCount = 30;

        for (let i = 0; i < particleCount; i += 1) {
            const particle = document.createElement("div");
            particle.className = "particle";
            particle.style.left = `${Math.random() * 100}%`;
            particle.style.animationDelay = `${Math.random() * 8}s`;
            particle.style.animationDuration = `${6 + Math.random() * 4}s`;
            container.appendChild(particle);
        }
    },

    initLightning() {
        const triggerLightning = () => {
            this.elements.lightning.classList.add("flash");
            setTimeout(() => {
                this.elements.lightning.classList.remove("flash");
            }, 50);

            if (Math.random() > 0.5) {
                setTimeout(() => {
                    this.elements.lightning.classList.add("flash");
                    setTimeout(() => {
                        this.elements.lightning.classList.remove("flash");
                    }, 50);
                }, 100);
            }

            setTimeout(triggerLightning, 10000 + Math.random() * 20000);
        };

        setTimeout(triggerLightning, 5000);
    },

    bindKeyboardEvents() {
        this.elements.commandInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                this.submitCommand();
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                this.navigateHistory(-1);
            } else if (event.key === "ArrowDown") {
                event.preventDefault();
                this.navigateHistory(1);
            }
        });
    },

    navigateHistory(direction) {
        if (this.commandHistory.length === 0) return;

        this.historyIndex += direction;

        if (this.historyIndex < 0) {
            this.historyIndex = 0;
        } else if (this.historyIndex >= this.commandHistory.length) {
            this.historyIndex = this.commandHistory.length;
            this.elements.commandInput.value = "";
            return;
        }

        this.elements.commandInput.value = this.commandHistory[this.historyIndex];
    },

    submitCommand() {
        const command = this.elements.commandInput.value.trim();
        if (!command) return;

        this.commandHistory.push(command);
        this.historyIndex = this.commandHistory.length;
        this.elements.commandInput.value = "";

        if (typeof window.onGameCommand === "function") {
            window.onGameCommand(command);
        }
    },

    addMessage(command, response, isError = false, isGameOver = false) {
        const messageDiv = document.createElement("div");
        messageDiv.className = "message";

        if (command) {
            const commandDiv = document.createElement("div");
            commandDiv.className = "message-command";
            commandDiv.textContent = `> ${command}`;
            messageDiv.appendChild(commandDiv);
        }

        const responseDiv = document.createElement("div");
        responseDiv.className = "message-response";

        if (isError) {
            responseDiv.classList.add("error");
        } else if (isGameOver) {
            responseDiv.classList.add("game-over");
        } else {
            responseDiv.classList.add("success");
        }

        responseDiv.innerHTML = this.formatMessage(response);
        messageDiv.appendChild(responseDiv);

        this.elements.gameOutput.appendChild(messageDiv);
        this.scrollToBottom();
    },

    addPureMessage(response, className = "") {
        const messageDiv = document.createElement("div");
        messageDiv.className = "message";

        const responseDiv = document.createElement("div");
        responseDiv.className = `message-response ${className}`.trim();
        responseDiv.innerHTML = this.formatMessage(response);
        messageDiv.appendChild(responseDiv);

        this.elements.gameOutput.appendChild(messageDiv);
        this.scrollToBottom();
    },

    formatMessage(text) {
        let formatted = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        formatted = formatted.replace(/"([^"]+)"/g, "{{INTERACTABLE_START}}$1{{INTERACTABLE_END}}");
        formatted = formatted.replace(/(^|[^A-Za-z])'([^'\n]+)'(?=[^A-Za-z]|$)/g, "$1{{PORTABLE_START}}$2{{PORTABLE_END}}");
        formatted = formatted.replace(/\[(.+?)\]/g, "{{ROOM_START}}[$1]{{ROOM_END}}");

        formatted = formatted.replace(/\{\{INTERACTABLE_START\}\}/g, '<em class="item-interactable">');
        formatted = formatted.replace(/\{\{INTERACTABLE_END\}\}/g, "</em>");
        formatted = formatted.replace(/\{\{PORTABLE_START\}\}/g, '<em class="item-portable">');
        formatted = formatted.replace(/\{\{PORTABLE_END\}\}/g, "</em>");
        formatted = formatted.replace(/\{\{ROOM_START\}\}/g, '<span class="room-title">');
        formatted = formatted.replace(/\{\{ROOM_END\}\}/g, "</span>");

        return formatted.replace(/\n/g, "<br>");
    },

    scrollToBottom() {
        const output = this.elements.gameOutput;
        setTimeout(() => {
            output.scrollTop = output.scrollHeight;
        }, 50);
    },

    clearOutput() {
        this.elements.gameOutput.innerHTML = "";
    },

    updateState(state) {
        if (!state) return;

        if (state.room) {
            this.elements.currentRoom.textContent = state.room.name;
            this.updateExits(state.room.exits, state.room.dark);
        }

        this.updateInventory(state.inventory);

        if (typeof state.turn_count !== "undefined") {
            this.elements.turnCount.textContent = state.turn_count;
        }

        this.updateLightStatus(state.can_see, state.inventory);
        this.updateKeyFragments(state.inventory, state.flags);
    },

    updateExits(exits, isDark) {
        const exitButtons = this.elements.exitsGrid.querySelectorAll(".exit-btn");

        exitButtons.forEach((btn) => {
            const direction = btn.dataset.direction;
            if (direction === "look") return;

            const hasExit = exits && exits.includes(direction);
            btn.disabled = !hasExit;
            btn.title = isDark && hasExit ? "An exit fading through the dark" : "";
        });
    },

    updateInventory(inventory) {
        const list = this.elements.inventoryList;
        list.innerHTML = "";

        if (!inventory || inventory.length === 0) {
            const emptyItem = document.createElement("li");
            emptyItem.className = "empty-slot";
            emptyItem.textContent = "Empty";
            list.appendChild(emptyItem);
        } else {
            inventory.forEach((item) => {
                const entry = document.createElement("li");
                entry.textContent = item.name;
                entry.dataset.itemId = item.id;

                if (item.state && item.state.lit) {
                    entry.classList.add("item-lit");
                }

                entry.addEventListener("click", () => {
                    this.elements.commandInput.value = `examine ${item.name}`;
                    this.elements.commandInput.focus();
                });

                list.appendChild(entry);
            });
        }

        const count = inventory ? inventory.length : 0;
        this.elements.inventoryCount.textContent = `${count}/6`;
    },

    updateLightStatus(canSee, inventory) {
        const hasLight = inventory && inventory.some((item) => item.state && item.state.lit);

        if (hasLight) {
            this.elements.lightStatus.classList.add("has-light");
            this.elements.lightText.textContent = "Light source active";
        } else {
            this.elements.lightStatus.classList.remove("has-light");
            this.elements.lightText.textContent = canSee === false ? "In darkness" : "No light";
        }
    },

    updateKeyFragments(inventory, flags) {
        const fragmentA = document.getElementById("fragment-a");
        const fragmentB = document.getElementById("fragment-b");
        const fragmentC = document.getElementById("fragment-c");

        const hasFragmentA = inventory && inventory.some((item) => item.id === "key_fragment_a");
        const hasFragmentB = inventory && inventory.some((item) => item.id === "key_fragment_b");
        const hasFragmentC = inventory && inventory.some((item) => item.id === "key_fragment_c");
        const hasCompleteKey = inventory && inventory.some((item) => item.id === "complete_key");

        if (hasCompleteKey || (flags && flags.key_assembled)) {
            fragmentA.classList.add("collected");
            fragmentB.classList.add("collected");
            fragmentC.classList.add("collected");
        } else {
            fragmentA.classList.toggle("collected", hasFragmentA);
            fragmentB.classList.toggle("collected", hasFragmentB);
            fragmentC.classList.toggle("collected", hasFragmentC);
        }
    },

    enableInput() {
        this.elements.commandInput.disabled = false;
        this.elements.sendBtn.disabled = false;
        this.elements.newGameBtn.classList.add("hidden");
        this.elements.commandInput.focus();
    },

    disableInput() {
        this.elements.commandInput.disabled = true;
        this.elements.sendBtn.disabled = true;
    },

    showLoading() {
        this.disableInput();
    },

    hideLoading() {
        // Intentionally left blank. Input is re-enabled by the caller.
    },

    showGameOver() {
        this.disableInput();
        this.elements.newGameBtn.classList.remove("hidden");
        this.elements.newGameBtn.textContent = "Play Again";
    },
};

window.GameUI = UI;
