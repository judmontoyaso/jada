document.addEventListener('DOMContentLoaded', () => {
    // Obtener el ID de la URL
    const urlParams = new URLSearchParams(window.location.search);
    const lessonId = urlParams.get('id');

    if (!lessonId) {
        document.getElementById('lesson-header').innerHTML = '<h2>Error: No se seleccionó ninguna lección.</h2>';
        setTimeout(() => window.location.href = 'index.html', 3000);
        return;
    }

    fetch('storyline.json')
        .then(response => response.json())
        .then(data => {
            const lesson = data.find(item => item.id === lessonId);

            if (!lesson) {
                document.getElementById('lesson-header').innerHTML = '<h2>Error: Lección no encontrada.</h2>';
                return;
            }

            renderLesson(lesson);
        })
        .catch(error => {
            console.error('Error fetching lesson data:', error);
            document.getElementById('lesson-header').innerHTML = '<p style="color:red;">Error al cargar la lección.</p>';
        });
});

function renderLesson(lesson) {
    // Pintar el header con badge titular dinámico
    const headerHtml = `
        <span class="event-badge">${lesson.badge}</span>
        <!-- El título H1 real proviene del Markdown, pero si fuesen distintos lo pintaríamos aquí. -->
    `;

    // Parsear el Markdown.
    // Marcamos enable highlighting via MarkedJS options
    marked.setOptions({
        highlight: function (code, lang) {
            const language = hljs.getLanguage(lang) ? lang : 'plaintext';
            return hljs.highlight(code, { language }).value;
        },
        langPrefix: 'hljs language-'
    });

    const parsedHtml = marked.parse(lesson.details_markdown || "### Esta lección aún no tiene contenido detallado.");

    document.getElementById('lesson-header').innerHTML = headerHtml;
    document.getElementById('markdown-content').innerHTML = parsedHtml;

    // Colorear dinámicamente el badge de la cabecera
    const headerElement = document.getElementById('lesson-header');
    headerElement.dataset.type = lesson.type;

    // Apply Rough Notation
    if (typeof RoughNotation !== 'undefined') {
        const ag = [];
        // Annotate the main H1
        const mainH1 = document.querySelector('.markdown-body h1');
        if (mainH1) {
            ag.push(RoughNotation.annotate(mainH1, {
                type: 'highlight',
                color: 'rgba(14, 165, 233, 0.15)', // light blue
                animationDuration: 800,
                iterations: 1,
                multiline: true
            }));
        }

        // Annotate all H2 subheadings with an underline
        const h2s = document.querySelectorAll('.markdown-body h2');
        h2s.forEach(h2 => {
            ag.push(RoughNotation.annotate(h2, {
                type: 'underline',
                color: '#7c3aed', // purple
                strokeWidth: 2,
                animationDuration: 600
            }));
        });

        if (ag.length > 0) {
            RoughNotation.annotationGroup(ag).show();
        }
    }
}
