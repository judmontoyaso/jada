document.addEventListener('DOMContentLoaded', () => {
    // Start terminal typing effect
    startTerminalAnimation();

    // Fetch and render the timeline
    fetch('storyline.json')
        .then(response => response.json())
        .then(data => {
            renderStoryline(data);
            setupIntersectionObserver();
            setupCardClicks();
        })
        .catch(error => {
            console.error('Error fetching storyline:', error);
            const container = document.getElementById('timeline-events');
            if (container) {
                container.innerHTML = '<p style="text-align:center; color:red;">Error al cargar la clase. Asegúrate de tener el servidor activo (python3 -m http.server 8000).</p>';
            }
        });
});

function startTerminalAnimation() {
    const asciiArt = `
     ██╗ █████╗ ██████╗  █████╗
     ██║██╔══██╗██╔══██╗██╔══██╗
     ██║███████║██║  ██║███████║
██   ██║██╔══██║██║  ██║██╔══██║
╚█████╔╝██║  ██║██████╔╝██║  ██║
 ╚════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝
`;

    const subtitleText = "> Caso de estudio empírico: La evolución arquitectónica de un Agente IA autónomo. Lecciones de trinchera sobre persistencia de memoria, ruteo semántico de herramientas y control de alucinaciones.";

    const asciiElement = document.getElementById('ascii-art');
    const textElement = document.getElementById('terminal-text');

    if (!asciiElement || !textElement) return;

    let i = 0;

    // Type the ASCII art fast
    function typeAscii() {
        if (i < asciiArt.length) {
            asciiElement.innerHTML += asciiArt.charAt(i);
            i++;
            setTimeout(typeAscii, 5); // very fast for ASCII
        } else {
            // Once ASCII is done, start typing the paragraph
            setTimeout(typeText, 500);
        }
    }

    let j = 0;
    // Type the description like a human
    function typeText() {
        if (j < subtitleText.length) {
            textElement.innerHTML += subtitleText.charAt(j);
            j++;
            setTimeout(typeText, 30); // moderate typing speed
        } else {
            // typing done! Start random glitching
            startGlitchInterval();
        }
    }

    typeAscii();
}

function startGlitchInterval() {
    const terminal = document.querySelector('.hacker-terminal');
    if (!terminal) return;

    setInterval(() => {
        // randomly trigger glitch 10% of the time every 2 seconds
        if (Math.random() < 0.1) {
            terminal.classList.add('glitch-effect');
            setTimeout(() => terminal.classList.remove('glitch-effect'), 200);
        }
    }, 2000);
}

function renderStoryline(storyline) {
    const container = document.getElementById('timeline-events');
    let html = '';

    storyline.forEach((step, index) => {
        // Agregamos data-id a la tarjeta y le damos estilo cliqueable
        html += `
            <div class="event" data-type="${step.type}">
                <div class="event-dot"></div>
                <!-- Ahora es clickable -->
                <div class="event-content educational-card clickable-card" data-id="${step.id}" tabindex="0">
                    <div class="card-header">
                        <span class="event-badge">${step.badge}</span>
                        <h2 class="event-title">${step.title}</h2>
                    </div>
                    
                    <div class="educational-section concept">
                        <h3>📖 Concepto Técnico</h3>
                        <p>${step.concept}</p>
                    </div>

                    <div class="educational-section problem">
                        <h3>⚠️ El Problema</h3>
                        <p>${step.problem}</p>
                    </div>

                    <div class="educational-section solution">
                        <h3>✅ La Solución en Jada</h3>
                        <p>${step.solution}</p>
                    </div>
                    
                    <div class="card-footer">
                        <span>Leer Lección Completa ➞</span>
                    </div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function setupCardClicks() {
    const cards = document.querySelectorAll('.clickable-card');
    cards.forEach(card => {
        card.addEventListener('click', () => {
            const lessonId = card.getAttribute('data-id');
            // Redirigir enviando el ID por URL parameters
            window.location.href = `lesson.html?id=${lessonId}`;
        });

        // Accesibilidad: Enter para abrir
        card.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const lessonId = card.getAttribute('data-id');
                window.location.href = `lesson.html?id=${lessonId}`;
            }
        });
    });
}

function setupIntersectionObserver() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');

                // Trigger Rough Notation on the title if not already annotated
                if (!entry.target.dataset.annotated) {
                    const title = entry.target.querySelector('.event-title');
                    if (title && typeof RoughNotation !== 'undefined') {
                        const annotation = RoughNotation.annotate(title, {
                            type: 'highlight',
                            color: 'rgba(124, 58, 237, 0.15)', // Light purple highlight
                            animationDuration: 800,
                            iterations: 1,
                            multiline: true
                        });
                        annotation.show();
                        entry.target.dataset.annotated = 'true';
                    }
                }
            }
        });
    }, {
        threshold: 0.15,
        rootMargin: "0px 0px -50px 0px"
    });

    document.querySelectorAll('.event').forEach(event => {
        observer.observe(event);
    });
}
