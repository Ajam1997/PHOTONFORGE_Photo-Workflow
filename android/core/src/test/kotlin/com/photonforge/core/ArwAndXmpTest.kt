package com.photonforge.core

import com.photonforge.core.arw.ArwPreview
import com.photonforge.core.xmp.XmpSidecar
import javax.xml.parsers.DocumentBuilderFactory
import java.io.ByteArrayInputStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class ArwAndXmpTest {

    // ------------------------------------------------------------------ ARW
    @Test
    fun parsesLargestPreviewAndExifFromSyntheticTiff() {
        val bytes = javaClass.classLoader.getResourceAsStream("fixtures/synthetic.tiff")!!.readBytes()
        val result = ArwPreview.parse(bytes)
        // The SubIFD carries the 1024-byte preview; IFD0 a 256-byte one; IFD1 64.
        assertEquals(1024L, result.previewLength)
        assertEquals(3, result.allPreviews.size)
        assertEquals("2026:07:17 10:00:00", result.dateTimeOriginal)
        assertEquals(0.5, result.exposureSeconds!!, 1e-9)
        // The preview bytes are a JPEG (SOI marker).
        val off = result.previewOffset.toInt()
        assertEquals(0xFF, bytes[off].toInt() and 0xFF)
        assertEquals(0xD8, bytes[off + 1].toInt() and 0xFF)
    }

    @Test
    fun rejectsNonTiff() {
        val bad = ByteArray(16) { 0x42 }
        var threw = false
        try {
            ArwPreview.parse(bad)
        } catch (e: IllegalArgumentException) {
            threw = true
        }
        assertTrue(threw)
    }

    // ------------------------------------------------------------------ XMP
    private fun sampleData(rating: Int = 4) = XmpSidecar.SidecarData(
        fusion = FusionResult(
            masterScore = 0.61,
            subject = "wildlife",
            subjectConfidence = 0.83,
            photoType = "scenic",
            typeConfidence = 0.44,
            subScores = mapOf(
                "eye_sharpness" to 0.9, "subject_sharpness" to 0.8,
                "subject_isolation" to 0.5, "composition_rot" to 0.6,
                "symmetry" to 0.2, "leading_lines" to 0.1,
                "negative_space" to 0.7, "zone_entropy" to 0.75,
                "dynamic_range" to 0.65, "face_exposure" to 0.5,
                "aesthetic_clip" to 0.55, "exposure_overall" to 0.8,
            ),
            hardReject = false,
            hardRejectReason = "",
            starRating = 4,
            colorLabel = 2,
            needsReview = true,
        ),
        semanticName = "eagle_over_fjord",
        originalFilename = "DSC01234.ARW",
        sessionId = "session_0003",
        isDuplicate = false,
        rating = rating,
        sharpnessOverall = 0.77,
        compositionOverall = 0.52,
        exposureOverall = 0.8,
        blurType = "bokeh",
        exposureStyle = "normal",
    )

    private val darktableSidecar = """
        <x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
         <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
          <rdf:Description rdf:about=""
            xmlns:xmp="http://ns.adobe.com/xap/1.0/"
            xmlns:darktable="http://darktable.sf.net/"
            xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmp:Rating="2"
            darktable:xmp_version="5"
            darktable:history_end="1">
           <darktable:history>
            <rdf:Seq>
             <rdf:li darktable:operation="exposure" darktable:params="abc123"/>
            </rdf:Seq>
           </darktable:history>
           <dc:subject>
            <rdf:Bag>
             <rdf:li>holiday</rdf:li>
             <rdf:li>photon|subject|people</rdf:li>
            </rdf:Bag>
           </dc:subject>
          </rdf:Description>
         </rdf:RDF>
        </x:xmpmeta>
    """.trimIndent()

    private fun parseXml(text: String): org.w3c.dom.Document {
        val body = text.lines().filterNot { it.startsWith("<?xpacket") }.joinToString("\n")
        val dbf = DocumentBuilderFactory.newInstance()
        dbf.isNamespaceAware = true
        return dbf.newDocumentBuilder().parse(ByteArrayInputStream(body.toByteArray()))
    }

    @Test
    fun freshSidecarCarriesPhotonAndStandardProperties() {
        val text = XmpSidecar.render(null, sampleData())
        assertTrue(text.startsWith("<?xpacket begin="))
        val doc = parseXml(text)
        val desc = doc.getElementsByTagNameNS(XmpSidecar.RDF_NS, "Description").item(0) as org.w3c.dom.Element
        assertEquals("4", desc.getAttributeNS(XmpSidecar.XMP_NS, "Rating"))
        assertEquals("Green", desc.getAttributeNS(XmpSidecar.XMP_NS, "Label"))
        assertTrue(text.contains(">wildlife<"))
        assertTrue(text.contains("photon|subject|wildlife"))
        assertTrue(text.contains("photon|type|scenic"))
        assertTrue(text.contains("photon|needs_review"))
        assertTrue(text.contains("eagle_over_fjord"))
        assertTrue(text.contains("DSC01234.ARW"))
    }

    @Test
    fun preservesDarktableHistoryAndForeignTags() {
        val text = XmpSidecar.render(darktableSidecar.toByteArray(), sampleData())
        val doc = parseXml(text)
        val desc = doc.getElementsByTagNameNS(XmpSidecar.RDF_NS, "Description").item(0) as org.w3c.dom.Element
        // darktable state intact
        assertEquals("1", desc.getAttributeNS("http://darktable.sf.net/", "history_end"))
        val hist = doc.getElementsByTagNameNS("http://darktable.sf.net/", "history")
        assertEquals(1, hist.length)
        assertTrue(text.contains("abc123"))
        // our rating replaced darktable's
        assertEquals("4", desc.getAttributeNS(XmpSidecar.XMP_NS, "Rating"))
        // foreign tag kept; stale photon subject tag replaced by the new one
        assertTrue(text.contains(">holiday<"))
        assertFalse(text.contains("photon|subject|people"))
        assertTrue(text.contains("photon|subject|wildlife"))
    }

    @Test
    fun rerenderIsIdempotent() {
        val once = XmpSidecar.render(null, sampleData())
        val twice = XmpSidecar.render(once.toByteArray(), sampleData())
        val doc = parseXml(twice)
        assertEquals(1, doc.getElementsByTagNameNS(XmpSidecar.PHOTON_NS, "SharpnessScore").length)
        assertEquals(1, doc.getElementsByTagNameNS(XmpSidecar.PHOTON_NS, "Genres").length)
        // one hierarchicalSubject bag with exactly our 3 photon tags
        val lr = doc.getElementsByTagNameNS(XmpSidecar.LR_NS, "hierarchicalSubject")
        assertEquals(1, lr.length)
    }

    @Test
    fun neverWritesPurpleLabel() {
        val data = sampleData().let {
            it.copy(fusion = it.fusion.copy(colorLabel = 4))
        }
        val text = XmpSidecar.render(null, data)
        assertFalse(text.contains("Purple"))
    }

    @Test
    fun sidecarNamingIsAppendStyle() {
        assertEquals("DSC01234.ARW.xmp", XmpSidecar.sidecarName("DSC01234.ARW"))
    }

    @Test
    fun corruptSidecarFallsBackToFresh() {
        val text = XmpSidecar.render("<not-xml".toByteArray(), sampleData())
        assertNotNull(parseXml(text))
        assertTrue(text.contains("photon|subject|wildlife"))
    }
}
